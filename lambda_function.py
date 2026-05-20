#!/usr/bin/env python3
"""
AWS IAM Identity Center (SSO) Permissions Export - Lambda Function
Exports SSO users and permission sets as CSV files to S3 bucket.

No external dependencies required - uses only boto3 and Python standard library.
"""

import boto3
import csv
from botocore.exceptions import ClientError
from io import StringIO
from datetime import datetime
import logging
import os

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# S3 bucket name
S3_BUCKET = os.environ.get('S3_BUCKET', 'aws-sso-users-and-permission-exporter')


def get_identity_store_id(sso_admin_client):
    """Get the Identity Store ID from SSO instance"""
    response = sso_admin_client.list_instances()
    if response['Instances']:
        return response['Instances'][0]['IdentityStoreId'], response['Instances'][0]['InstanceArn']
    else:
        raise Exception("No SSO instances found")


def get_all_users(identitystore_client, identity_store_id):
    """Get all users from Identity Store"""
    users = []
    paginator = identitystore_client.get_paginator('list_users')
    for page in paginator.paginate(IdentityStoreId=identity_store_id):
        users.extend(page['Users'])
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
        logger.error(f"Error getting account assignments: {e}")
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
            pass

        return ps_name, aws_managed, customer_managed
    except ClientError as e:
        logger.error(f"Error getting permission set details: {e}")
        return None, [], []


def upload_to_s3(s3_client, bucket, key, body, content_type):
    """Upload file to S3"""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type
    )
    logger.info(f"Uploaded to s3://{bucket}/{key}")


def write_csv_to_buffer(headers, rows):
    """Write data to a CSV string buffer"""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def lambda_handler(event, context):
    """Lambda entry point"""
    logger.info("Starting AWS SSO permissions export...")

    # Initialize clients
    sso_admin_client = boto3.client('sso-admin')
    identitystore_client = boto3.client('identitystore')
    org_client = boto3.client('organizations')
    s3_client = boto3.client('s3')

    # Get Identity Store ID and Instance ARN
    logger.info("Getting SSO instance details...")
    identity_store_id, instance_arn = get_identity_store_id(sso_admin_client)
    logger.info(f"Identity Store ID: {identity_store_id}")
    logger.info(f"Instance ARN: {instance_arn}")

    # Get all users
    logger.info("Fetching all users...")
    users = get_all_users(identitystore_client, identity_store_id)
    logger.info(f"Found {len(users)} users")

    # Create user lookup dictionary
    user_lookup = {user['UserId']: user['UserName'] for user in users}

    # Get all accounts
    logger.info("Fetching all accounts...")
    accounts = []
    paginator = org_client.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend(page['Accounts'])
    logger.info(f"Found {len(accounts)} accounts")

    # Collect all permission data
    logger.info("Collecting permission data...")
    data = []

    for account in accounts:
        account_id = account['Id']
        account_name = account['Name']
        logger.info(f"Processing account: {account_name} ({account_id})")

        try:
            ps_paginator = sso_admin_client.get_paginator('list_permission_sets_provisioned_to_account')
            for ps_page in ps_paginator.paginate(
                InstanceArn=instance_arn,
                AccountId=account_id
            ):
                for permission_set_arn in ps_page.get('PermissionSets', []):
                    ps_name, aws_managed, customer_managed = get_permission_set_details(
                        sso_admin_client, instance_arn, permission_set_arn
                    )

                    if not ps_name:
                        continue

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
            logger.error(f"Error processing account {account_id}: {e}")
            continue

    # Create CSV output
    logger.info(f"Creating output with {len(data)} permission records...")

    # Sort data by User, Account Name
    data.sort(key=lambda x: (x['User'], x['Account Name']))

    # Main permissions CSV
    permissions_headers = ['Sr. No', 'User', 'Account ID', 'Account Name', 'Permission Set', 'AWS Managed Policies', 'Customer Managed Policies']
    permissions_rows = []
    for idx, record in enumerate(data, 1):
        permissions_rows.append([
            idx,
            record['User'],
            record['Account ID'],
            record['Account Name'],
            record['Permission Set'],
            record['AWS Managed Policies'],
            record['Customer Managed Policies']
        ])

    # Users CSV
    users_headers = ['Sr. No', 'User ID', 'User Name', 'Display Name', 'Email']
    users_rows = []
    for idx, user in enumerate(users, 1):
        users_rows.append([
            idx,
            user['UserId'],
            user['UserName'],
            user.get('DisplayName', ''),
            user['Emails'][0]['Value'] if user.get('Emails') else ''
        ])

    # Permission Sets CSV
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
                for permission_set_arn in ps_page.get('PermissionSets', []):
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

    permission_sets_data.sort(key=lambda x: x['Permission Set'])
    ps_headers = ['Sr. No', 'Permission Set', 'Permission Set ARN', 'AWS Managed Policies', 'Customer Managed Policies']
    ps_rows = []
    for idx, ps in enumerate(permission_sets_data, 1):
        ps_rows.append([
            idx,
            ps['Permission Set'],
            ps['Permission Set ARN'],
            ps['AWS Managed Policies'],
            ps['Customer Managed Policies']
        ])

    # Generate S3 path: Year/Month/filename_date_month_year.csv
    now = datetime.utcnow()
    year = now.strftime('%Y')
    month = now.strftime('%m')
    date_suffix = now.strftime('%d_%m_%Y')

    # Upload CSVs to S3
    # User Permissions
    permissions_csv = write_csv_to_buffer(permissions_headers, permissions_rows)
    permissions_key = f"{year}/{month}/AWS_SSO_User_Permissions_{date_suffix}.csv"
    upload_to_s3(s3_client, S3_BUCKET, permissions_key, permissions_csv, 'text/csv')

    # All Users
    users_csv = write_csv_to_buffer(users_headers, users_rows)
    users_key = f"{year}/{month}/AWS_SSO_All_Users_{date_suffix}.csv"
    upload_to_s3(s3_client, S3_BUCKET, users_key, users_csv, 'text/csv')

    # Permission Sets
    ps_csv = write_csv_to_buffer(ps_headers, ps_rows)
    ps_key = f"{year}/{month}/AWS_SSO_Permission_Sets_{date_suffix}.csv"
    upload_to_s3(s3_client, S3_BUCKET, ps_key, ps_csv, 'text/csv')

    result = {
        'statusCode': 200,
        'body': {
            'message': 'SSO permissions export completed successfully',
            'bucket': S3_BUCKET,
            'files': {
                'permissions': f"s3://{S3_BUCKET}/{permissions_key}",
                'users': f"s3://{S3_BUCKET}/{users_key}",
                'permission_sets': f"s3://{S3_BUCKET}/{ps_key}"
            },
            'stats': {
                'total_users': len(users),
                'total_accounts': len(accounts),
                'total_permission_records': len(data),
                'total_permission_sets': len(permission_sets_data)
            }
        }
    }

    logger.info(f"Export complete: {result['body']['stats']}")
    return result
