# How It Works

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                            │
│                                                                                  │
│  ┌─────────────┐         ┌─────────────────────┐         ┌───────────────────┐  │
│  │ EventBridge │         │   Lambda Function    │         │    S3 Bucket      │  │
│  │  Schedule   │────────▶│  (Python 3.11)       │────────▶│ aws-sso-users-and │  │
│  │             │ Trigger │                      │  CSV    │ -permission-      │  │
│  │ cron(0 0 1  │         │ lambda_function.py   │  Upload │  exporter         │  │
│  │   * ? *)    │         │                      │         │                   │  │
│  └─────────────┘         └──────────┬───────────┘         │ /2026/06/         │  │
│                                     │                     │   ├── Users.csv   │  │
│                    ┌────────────────┼────────────────┐    │   ├── Perms.csv   │  │
│                    │                │                │    │   └── Sets.csv    │  │
│                    ▼                ▼                ▼    └───────────────────┘  │
│           ┌──────────────┐ ┌──────────────┐ ┌───────────┐                       │
│           │ IAM Identity │ │    AWS       │ │ CloudWatch│                       │
│           │   Center     │ │Organizations │ │   Logs    │                       │
│           │   (SSO)      │ │              │ │           │                       │
│           │              │ │              │ │           │                       │
│           │ • Users      │ │ • Accounts   │ │ • Logs    │                       │
│           │ • Permission │ │ • Account    │ │ • Errors  │                       │
│           │   Sets       │ │   Names      │ │ • Stats   │                       │
│           │ • Assignments│ │              │ │           │                       │
│           └──────────────┘ └──────────────┘ └───────────┘                       │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Execution Flow

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌─────────┐
│  START  │────▶│ Get SSO  │────▶│ Get All  │────▶│ Get All  │────▶│ Loop    │
│(trigger)│     │ Instance │     │  Users   │     │ Accounts │     │Accounts │
└─────────┘     └──────────┘     └──────────┘     └──────────┘     └────┬────┘
                                                                         │
                    ┌────────────────────────────────────────────────────┘
                    ▼
            ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
            │ Get Perm Sets│────▶│Get Assignments│────▶│ Build CSV    │
            │ per Account  │     │ per Perm Set │     │   Records    │
            └──────────────┘     └──────────────┘     └──────┬───────┘
                                                              │
                    ┌─────────────────────────────────────────┘
                    ▼
            ┌──────────────┐     ┌──────────────┐     ┌─────────┐
            │ Generate CSV │────▶│ Upload to S3 │────▶│  DONE   │
            │   Files      │     │  Bucket      │     │(return) │
            └──────────────┘     └──────────────┘     └─────────┘
```

---

## Explaination

### Block 1: Imports and Configuration

```python
import boto3
import csv
from botocore.exceptions import ClientError
from io import StringIO
from datetime import datetime
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get('S3_BUCKET', 'aws-sso-users-and-permission-exporter')
```

**What it does:**
- Imports only standard library modules and `boto3` (pre-installed in Lambda runtime) — no external dependencies needed
- `csv` and `StringIO` are used to generate CSV files in memory
- `S3_BUCKET` is read from environment variables, defaulting to `aws-sso-users-and-permission-exporter`
- Logging is configured to output to CloudWatch Logs

---

### Block 2: `get_identity_store_id()`

```python
def get_identity_store_id(sso_admin_client):
    response = sso_admin_client.list_instances()
    if response['Instances']:
        return response['Instances'][0]['IdentityStoreId'], response['Instances'][0]['InstanceArn']
    else:
        raise Exception("No SSO instances found")
```

**What it does:**
- Calls the SSO Admin API to discover the Identity Center instance
- Returns two values:
  - **Identity Store ID** — needed to query users
  - **Instance ARN** — needed for all permission set operations
- Raises an exception if no SSO instance exists (Lambda will report this as a failure)

---

### Block 3: `get_all_users()`

```python
def get_all_users(identitystore_client, identity_store_id):
    users = []
    paginator = identitystore_client.get_paginator('list_users')
    for page in paginator.paginate(IdentityStoreId=identity_store_id):
        users.extend(page['Users'])
    return users
```

**What it does:**
- Uses pagination to fetch ALL users from the Identity Store (handles orgs with 100+ users)
- Returns a list of user objects containing UserId, UserName, DisplayName, and Emails

---

### Block 4: `get_account_assignments()`

```python
def get_account_assignments(sso_admin_client, instance_arn, account_id, permission_set_arn):
    assignments = []
    paginator = sso_admin_client.get_paginator('list_account_assignments')
    for page in paginator.paginate(
        InstanceArn=instance_arn,
        AccountId=account_id,
        PermissionSetArn=permission_set_arn
    ):
        assignments.extend(page['AccountAssignments'])
    return assignments
```

**What it does:**
- For a given account + permission set combination, fetches all user/group assignments
- Each assignment tells us which principal (user or group) has access to which account via which permission set
- Uses pagination to handle large numbers of assignments

---

### Block 5: `get_permission_set_details()`

```python
def get_permission_set_details(sso_admin_client, instance_arn, permission_set_arn):
    # 1. Describe the permission set to get its name
    # 2. List AWS managed policies attached
    # 3. List customer managed policies attached
    return ps_name, aws_managed, customer_managed
```

**What it does:**
- Takes a permission set ARN and retrieves:
  - **Name** — human-readable name (e.g., "AdministratorAccess")
  - **AWS Managed Policies** — AWS-provided policies (e.g., "AmazonS3ReadOnlyAccess")
  - **Customer Managed Policies** — custom policies created in the account
- Handles errors gracefully if customer managed policies API is unavailable

---

### Block 6: `upload_to_s3()` and `write_csv_to_buffer()`

```python
def upload_to_s3(s3_client, bucket, key, body, content_type):
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)

def write_csv_to_buffer(headers, rows):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()
```

**What it does:**
- `write_csv_to_buffer` — creates a CSV file entirely in memory (no disk I/O needed)
- `upload_to_s3` — uploads the in-memory CSV content directly to S3 using `put_object`

---

### Block 7: `lambda_handler()` — Initialize Clients

```python
def lambda_handler(event, context):
    sso_admin_client = boto3.client('sso-admin')
    identitystore_client = boto3.client('identitystore')
    org_client = boto3.client('organizations')
    s3_client = boto3.client('s3')
```

**What it does:**
- Entry point for Lambda execution (triggered by EventBridge or manual test)
- Creates four AWS SDK clients:
  - `sso-admin` — permission sets and assignments
  - `identitystore` — user information
  - `organizations` — account listing
  - `s3` — file upload

---

### Block 8: `lambda_handler()` — Fetch SSO Data

```python
    identity_store_id, instance_arn = get_identity_store_id(sso_admin_client)
    users = get_all_users(identitystore_client, identity_store_id)
    user_lookup = {user['UserId']: user['UserName'] for user in users}

    accounts = []
    paginator = org_client.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend(page['Accounts'])
```

**What it does:**
- Discovers the SSO instance
- Fetches all users and creates a lookup dictionary (UserId → UserName) for fast resolution later
- Fetches all AWS accounts from Organizations

---

### Block 9: `lambda_handler()` — Main Data Collection Loop

```python
    for account in accounts:
        # For each account:
        #   1. Get all permission sets provisioned to this account
        #   2. For each permission set, get its details (name, policies)
        #   3. Get all user assignments for this permission set + account
        #   4. For each USER assignment, record the data
```

**What it does:**
- This is the core logic — a nested loop that maps the relationship:
  - **Account** → **Permission Sets** → **User Assignments**
- For each user assignment found, it records:
  - Username, Account ID, Account Name, Permission Set Name, AWS Managed Policies, Customer Managed Policies
- Skips GROUP assignments (only captures direct USER assignments)
- Handles API errors per-account so one failure doesn't stop the entire export

---

### Block 10: `lambda_handler()` — Generate and Upload CSVs

```python
    now = datetime.utcnow()
    year = now.strftime('%Y')
    month = now.strftime('%m')
    date_suffix = now.strftime('%d_%m_%Y')

    permissions_key = f"{year}/{month}/AWS_SSO_User_Permissions_{date_suffix}.csv"
    users_key = f"{year}/{month}/AWS_SSO_All_Users_{date_suffix}.csv"
    ps_key = f"{year}/{month}/AWS_SSO_Permission_Sets_{date_suffix}.csv"
```

**What it does:**
- Generates the S3 key path using the current UTC date
- Creates three separate CSV files:
  1. **User Permissions** — who has access to what, with which policies
  2. **All Users** — complete user directory with emails
  3. **Permission Sets** — all permission sets with their attached policies
- Uploads each CSV to S3 under the `Year/Month/` prefix

---

### Block 11: `lambda_handler()` — Return Response

```python
    result = {
        'statusCode': 200,
        'body': {
            'message': 'SSO permissions export completed successfully',
            'bucket': S3_BUCKET,
            'files': { ... },
            'stats': {
                'total_users': len(users),
                'total_accounts': len(accounts),
                'total_permission_records': len(data),
                'total_permission_sets': len(permission_sets_data)
            }
        }
    }
    return result
```

**What it does:**
- Returns a structured response with:
  - S3 paths of all uploaded files
  - Statistics (user count, account count, permission records, permission sets)
- This response is visible in CloudWatch Logs and in the Lambda test console

---

## Data Flow Summary

| Step | API Called | Data Retrieved |
|------|-----------|----------------|
| 1 | `sso-admin:ListInstances` | SSO Instance ARN, Identity Store ID |
| 2 | `identitystore:ListUsers` | All SSO users (paginated) |
| 3 | `organizations:ListAccounts` | All AWS accounts (paginated) |
| 4 | `sso-admin:ListPermissionSetsProvisionedToAccount` | Permission sets per account |
| 5 | `sso-admin:DescribePermissionSet` | Permission set name |
| 6 | `sso-admin:ListManagedPoliciesInPermissionSet` | AWS managed policies |
| 7 | `sso-admin:ListCustomerManagedPolicyReferencesInPermissionSet` | Customer managed policies |
| 8 | `sso-admin:ListAccountAssignments` | User-to-account-to-permission-set mapping |
| 9 | `s3:PutObject` | Upload CSV files |

## Key Design Decisions

- **No external dependencies** — The script uses only `boto3` (pre-installed in Lambda) and Python standard library. This means you can paste the code directly into the Lambda console without packaging or layers.
- **CSV over Excel** — Avoids the need for `pandas` and `openpyxl` libraries. CSV files are universally readable and lightweight.
- **In-memory processing** — All CSV generation happens in memory using `StringIO`. No `/tmp` filesystem usage, keeping the function stateless.
- **Pagination everywhere** — Every API call uses paginators to handle organizations of any size.
- **Graceful error handling** — Individual account failures are logged but don't stop the entire export.
- **Date-based S3 structure** — Files are organized by Year/Month for easy browsing and lifecycle policy management.
