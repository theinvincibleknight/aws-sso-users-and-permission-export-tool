## 🔎 Step-by-Step Code Explanation

### 1. **Initialization**
- The script starts by creating AWS clients using `boto3`:
  - `sso-admin` → to interact with IAM Identity Center (SSO).
  - `identitystore` → to fetch user information.
  - `organizations` → to fetch AWS accounts in the org.

```python
sso_admin_client = boto3.client('sso-admin')
identitystore_client = boto3.client('identitystore')
org_client = boto3.client('organizations')
```

---

### 2. **Get Identity Store ID and Instance ARN**
- Calls `list_instances()` on the `sso-admin` client.
- Extracts the **IdentityStoreId** and **InstanceArn** of the SSO instance.
- These are required for all subsequent API calls.

```python
identity_store_id, instance_arn = get_identity_store_id(sso_admin_client)
```

---

### 3. **Fetch All Users**
- Uses a paginator on `list_users` to fetch all users from the Identity Store.
- Builds a dictionary mapping `UserId` → `UserName` for quick lookups later.

```python
users = get_all_users(identitystore_client, identity_store_id)
user_lookup = {user['UserId']: user['UserName'] for user in users}
```

---

### 4. **Fetch All Accounts**
- Uses a paginator on `list_accounts` from AWS Organizations.
- Collects all accounts with their IDs and names.

```python
accounts = []
paginator = org_client.get_paginator('list_accounts')
for page in paginator.paginate():
    accounts.extend(page['Accounts'])
```

---

### 5. **Collect Permission Data**
For each account:
1. Lists all **permission sets provisioned to the account**.
2. For each permission set:
   - Retrieves its **name** and attached policies:
     - AWS-managed policies.
     - Customer-managed policies.
   - Lists all **account assignments** (users assigned to that permission set).
   - Records the mapping:  
     **User → Account → Permission Set → Policies**

```python
ps_paginator = sso_admin_client.get_paginator('list_permission_sets_provisioned_to_account')
for ps_page in ps_paginator.paginate(InstanceArn=instance_arn, AccountId=account_id):
    for permission_set_arn in ps_page['PermissionSets']:
        ps_name, aws_managed, customer_managed = get_permission_set_details(...)
        assignments = get_account_assignments(...)
```

---

### 6. **Prepare DataFrames**
The script organizes the collected data into three reports using **pandas**:

1. **User Permissions Report**  
   - Each row = User + Account + Permission Set + Policies.
   - Adds a serial number column.
   - Sorted by User and Account Name.

2. **All Users Report**  
   - Lists all users with details (ID, username, display name, email).

3. **Permission Sets Report**  
   - Lists all permission sets with ARN and attached policies.
   - Deduplicates permission sets across accounts.

---

### 7. **Export Results**
- Saves the **main report** to CSV:
  ```
  AWS_SSO_Users_with_Permissions.csv
  ```
- Saves all three reports into an Excel file with multiple sheets:
  ```
  AWS_SSO_Users_with_Permissions_Export.xlsx
  ```
  - Sheet 1: User Permissions  
  - Sheet 2: All Users  
  - Sheet 3: Permission Sets  

```python
df_main.to_csv(csv_filename, index=False)
with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
    df_main.to_excel(writer, sheet_name='User Permissions', index=False)
    df_users.to_excel(writer, sheet_name='All Users', index=False)
    df_permission_sets.to_excel(writer, sheet_name='Permission Sets', index=False)
```

---

## 📊 Example Flow

1. **Fetch SSO instance details** → IdentityStoreId + InstanceArn  
2. **Fetch users** → Build lookup dictionary  
3. **Fetch accounts** → List all AWS accounts  
4. **For each account** → Get permission sets → Get policies → Get assignments  
5. **Build reports** → Users, Permissions, Permission Sets  
6. **Export** → CSV + Excel with multiple sheets  

---

## ✅ Key Takeaways
- The script uses **paginators** to handle large datasets (users, accounts, permission sets).
- It gracefully handles missing data (e.g., customer-managed policies).
- It produces both **CSV** (simple) and **Excel** (multi-sheet, detailed) outputs.
- It’s designed for **auditing IAM Identity Center permissions** across all accounts in an AWS Organization.

---
