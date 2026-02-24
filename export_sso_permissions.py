#!/usr/bin/env python3
"""
AWS IAM Identity Center (SSO) Permissions Export Script
"""

import boto3
import pandas as pd
from botocore.exceptions import ClientError
import sys

def get_identity_store_id(sso_admin_client):
    """Get the Identity Store ID from SSO instance"""
    try:
        response = sso_admin_client.list_instances()
        if response['Instances']:
            return response['Instances'][0]['IdentityStoreId'], response['Instances'][0]['InstanceArn']
        else:
            print("No SSO instances found")
            sys.exit(1)
    except ClientError as e:
        print(f"Error getting SSO instance: {e}")
        sys.exit(1)

def get_all_users(identitystore_client, identity_store_id):
    """Get all users from Identity Store"""
    users = []
    try:
        paginator = identitystore_client.get_paginator('list_users')
        for page in paginator.paginate(IdentityStoreId=identity_store_id):
            users.extend(page['Users'])
    except ClientError as e:
        print(f"Error listing users: {e}")
    return users

def get_account_assignments(sso_admin_client, instance_arn, account_id, permission_set_arn):
    """Get account assignments for a permission set"""
    assignments = []
    try:
        paginator = sso_admin_client.get_paginator('list_account_assignments')
        for page in paginator.paginate(
            InstanceArn=instance_arn,
            AccountId=account_id,
            PermissionSetArn=permission_set_arn
        ):
            assignments.extend(page['AccountAssignments'])
    except ClientError as e:
        print(f"Error getting account assignments: {e}")
    return assignments

def get_permission_set_details(sso_admin_client, instance_arn, permission_set_arn):
    """Get permission set name and policies"""
    try:
        # Get permission set name
        ps_response = sso_admin_client.describe_permission_set(
            InstanceArn=instance_arn,
            PermissionSetArn=permission_set_arn
        )
        ps_name = ps_response['PermissionSet']['Name']
        
        # Get AWS managed policies
        aws_managed = []
        paginator = sso_admin_client.get_paginator('list_managed_policies_in_permission_set')
        for page in paginator.paginate(
            InstanceArn=instance_arn,
            PermissionSetArn=permission_set_arn
        ):
            aws_managed.extend([p['Name'] for p in page['AttachedManagedPolicies']])
        
        # Get customer managed policies
        customer_managed = []
        try:
            paginator = sso_admin_client.get_paginator('list_customer_managed_policy_references_in_permission_set')
            for page in paginator.paginate(
                InstanceArn=instance_arn,
                PermissionSetArn=permission_set_arn
            ):
                customer_managed.extend([p['Name'] for p in page['CustomerManagedPolicyReferences']])
        except ClientError:
            pass  # Customer managed policies might not be available
        
        return ps_name, aws_managed, customer_managed
    except ClientError as e:
        print(f"Error getting permission set details: {e}")
        return None, [], []

def get_account_name(org_client, account_id):
    """Get account name from Organizations"""
    try:
        response = org_client.describe_account(AccountId=account_id)
        return response['Account']['Name']
    except ClientError:
        return account_id  # Return ID if name not available

def main():
    print("Initializing AWS clients...")
    
    # Initialize clients
    sso_admin_client = boto3.client('sso-admin')
    identitystore_client = boto3.client('identitystore')
    org_client = boto3.client('organizations')
    
    # Get Identity Store ID and Instance ARN
    print("Getting SSO instance details...")
    identity_store_id, instance_arn = get_identity_store_id(sso_admin_client)
    print(f"Identity Store ID: {identity_store_id}")
    print(f"Instance ARN: {instance_arn}")
    
    # Get all users
    print("\nFetching all users...")
    users = get_all_users(identitystore_client, identity_store_id)
    print(f"Found {len(users)} users")
    
    # Create user lookup dictionary
    user_lookup = {user['UserId']: user['UserName'] for user in users}
    
    # Get all accounts
    print("\nFetching all accounts...")
    accounts = []
    try:
        paginator = org_client.get_paginator('list_accounts')
        for page in paginator.paginate():
            accounts.extend(page['Accounts'])
    except ClientError as e:
        print(f"Error listing accounts: {e}")
        sys.exit(1)
    
    print(f"Found {len(accounts)} accounts")
    
    # Collect all data
    print("\nCollecting permission data...")
    data = []
    
    for account in accounts:
        account_id = account['Id']
        account_name = account['Name']
        print(f"\nProcessing account: {account_name} ({account_id})")
        
        # Get all permission sets
        try:
            ps_paginator = sso_admin_client.get_paginator('list_permission_sets_provisioned_to_account')
            for ps_page in ps_paginator.paginate(
                InstanceArn=instance_arn,
                AccountId=account_id
            ):
                for permission_set_arn in ps_page['PermissionSets']:
                    # Get permission set details
                    ps_name, aws_managed, customer_managed = get_permission_set_details(
                        sso_admin_client, instance_arn, permission_set_arn
                    )
                    
                    if not ps_name:
                        continue
                    
                    print(f"  Permission Set: {ps_name}")
                    
                    # Get assignments for this permission set
                    assignments = get_account_assignments(
                        sso_admin_client, instance_arn, account_id, permission_set_arn
                    )
                    
                    for assignment in assignments:
                        if assignment['PrincipalType'] == 'USER':
                            user_id = assignment['PrincipalId']
                            user_name = user_lookup.get(user_id, user_id)
                            
                            data.append({
                                'User': user_name,
                                'Account ID': account_id,
                                'Account Name': account_name,
                                'Permission Set': ps_name,
                                'AWS Managed Policies': ', '.join(aws_managed) if aws_managed else '',
                                'Customer Managed Policies': ', '.join(customer_managed) if customer_managed else ''
                            })
        except ClientError as e:
            print(f"  Error processing account {account_id}: {e}")
            continue
    
    # Create DataFrame for main sheet
    print(f"\n\nCreating output file with {len(data)} records...")
    df_main = pd.DataFrame(data)
    
    # Add serial number
    df_main.insert(0, 'Sr. No', range(1, len(df_main) + 1))
    
    # Sort by User, Account Name
    df_main = df_main.sort_values(['User', 'Account Name'])
    
    # Create Users sheet
    print("Creating users list...")
    users_data = []
    for idx, user in enumerate(users, 1):
        users_data.append({
            'Sr. No': idx,
            'User ID': user['UserId'],
            'User Name': user['UserName'],
            'Display Name': user.get('DisplayName', ''),
            'Email': user['Emails'][0]['Value'] if user.get('Emails') else ''
        })
    df_users = pd.DataFrame(users_data)
    
    # Create Permission Sets sheet
    print("Creating permission sets list...")
    permission_sets_data = []
    processed_ps = set()
    
    for account in accounts:
        account_id = account['Id']
        try:
            ps_paginator = sso_admin_client.get_paginator('list_permission_sets_provisioned_to_account')
            for ps_page in ps_paginator.paginate(
                InstanceArn=instance_arn,
                AccountId=account_id
            ):
                for permission_set_arn in ps_page['PermissionSets']:
                    if permission_set_arn not in processed_ps:
                        processed_ps.add(permission_set_arn)
                        ps_name, aws_managed, customer_managed = get_permission_set_details(
                            sso_admin_client, instance_arn, permission_set_arn
                        )
                        if ps_name:
                            permission_sets_data.append({
                                'Permission Set': ps_name,
                                'Permission Set ARN': permission_set_arn,
                                'AWS Managed Policies': ', '.join(aws_managed) if aws_managed else '',
                                'Customer Managed Policies': ', '.join(customer_managed) if customer_managed else ''
                            })
        except ClientError:
            continue
    
    df_permission_sets = pd.DataFrame(permission_sets_data)
    df_permission_sets = df_permission_sets.sort_values('Permission Set')
    df_permission_sets.insert(0, 'Sr. No', range(1, len(df_permission_sets) + 1))
    
    # Export to CSV (main sheet only)
    csv_filename = 'AWS_SSO_Users_with_Permissions.csv'
    df_main.to_csv(csv_filename, index=False)
    print(f"✓ CSV exported to: {csv_filename}")
    
    # Export to Excel with multiple sheets
    excel_filename = 'AWS_SSO_Users_with_Permissions_Export.xlsx'
    with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
        df_main.to_excel(writer, sheet_name='User Permissions', index=False)
        df_users.to_excel(writer, sheet_name='All Users', index=False)
        df_permission_sets.to_excel(writer, sheet_name='Permission Sets', index=False)
    
    print(f"✓ Excel exported to: {excel_filename}")
    print(f"  - Sheet 1: User Permissions ({len(df_main)} records)")
    print(f"  - Sheet 2: All Users ({len(df_users)} users)")
    print(f"  - Sheet 3: Permission Sets ({len(df_permission_sets)} permission sets)")
    
    print(f"\nTotal permission records: {len(df_main)}")
    print("\nSample data:")
    print(df_main.head())

if __name__ == "__main__":
    main()
