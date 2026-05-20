# AWS SSO Users and Permission Sets Export Tool

An AWS Lambda function that exports IAM Identity Center (SSO) users, permission sets, and account assignments as CSV files to an S3 bucket. Scheduled to run automatically at the start of every month using Amazon EventBridge.

## Output

The function generates three CSV files saved to S3 with the following structure:

```
aws-sso-users-and-permission-exporter/
└── <Year>/
    └── <Month>/
        ├── AWS_SSO_User_Permissions_<DD_MM_YYYY>.csv
        ├── AWS_SSO_All_Users_<DD_MM_YYYY>.csv
        └── AWS_SSO_Permission_Sets_<DD_MM_YYYY>.csv
```

**Example:**
```
aws-sso-users-and-permission-exporter/
└── 2026/
    └── 06/
        ├── AWS_SSO_User_Permissions_01_06_2026.csv
        ├── AWS_SSO_All_Users_01_06_2026.csv
        └── AWS_SSO_Permission_Sets_01_06_2026.csv
```

## Files

| File | Description |
|------|-------------|
| `lambda_function.py` | Lambda function code (paste directly into Lambda console) |
| `iam_policy.json` | IAM policy for the Lambda execution role |

## Prerequisites

- AWS account with IAM Identity Center (SSO) enabled
- AWS Organizations configured
- S3 bucket: `aws-sso-users-and-permission-exporter` (create beforehand)
- Lambda function must be deployed in the **same region as your SSO instance**

## Deployment Steps

### 1. Create the S3 Bucket

```bash
aws s3 mb s3://aws-sso-users-and-permission-exporter --region <your-sso-region>
```

### 2. Create the IAM Role for Lambda

1. Go to **IAM > Roles > Create Role**
2. Select **AWS Service > Lambda**
3. Name it: `lambda-sso-permissions-exporter-role`
4. After creation, attach an inline policy using the contents of `iam_policy.json`

### 3. Create the Lambda Function

1. Go to **Lambda > Create Function**
2. Choose **Author from scratch**
3. Configuration:
   - **Function name:** `aws-sso-permissions-exporter`
   - **Runtime:** Python 3.11 (or later)
   - **Architecture:** x86_64
   - **Execution role:** Use the role created in Step 2
4. Paste the contents of `lambda_function.py` into the code editor
5. Under **Configuration > General configuration:**
   - **Timeout:** 15 minutes (900 seconds)
   - **Memory:** 512 MB
6. Under **Configuration > Environment variables**, add:
   - `S3_BUCKET` = `aws-sso-users-and-permission-exporter`

### 4. Test the Lambda Function

1. Create a test event with an empty JSON payload: `{}`
2. Click **Test**
3. Verify the CSV files appear in your S3 bucket

### 5. Set Up EventBridge Schedule (Monthly Trigger)

1. Go to **Amazon EventBridge > Schedules > Create schedule**
2. Configuration:
   - **Schedule name:** `monthly-sso-permissions-export`
   - **Schedule type:** Recurring schedule
   - **Schedule expression type:** Cron-based schedule
   - **Cron expression:** `cron(0 0 1 * ? *)`
     - This runs at **00:00 UTC on the 1st of every month**
   - **Flexible time window:** Off
3. Target:
   - **Target type:** AWS Lambda
   - **Function:** `aws-sso-permissions-exporter`
   - **Payload:** `{}`
4. Review and create the schedule

#### Alternative: Using AWS CLI

```bash
# Create the EventBridge rule
aws events put-rule \
  --name "monthly-sso-permissions-export" \
  --schedule-expression "cron(0 0 1 * ? *)" \
  --state ENABLED \
  --region <your-sso-region>

# Add Lambda as target
aws events put-targets \
  --rule "monthly-sso-permissions-export" \
  --targets "Id"="1","Arn"="arn:aws:lambda:<region>:<account-id>:function:aws-sso-permissions-exporter" \
  --region <your-sso-region>

# Grant EventBridge permission to invoke Lambda
aws lambda add-permission \
  --function-name aws-sso-permissions-exporter \
  --statement-id eventbridge-monthly-trigger \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:<region>:<account-id>:rule/monthly-sso-permissions-export \
  --region <your-sso-region>
```

## IAM Permissions Required

The Lambda execution role needs the following permissions (defined in `iam_policy.json`):

| Service | Actions | Purpose |
|---------|---------|---------|
| SSO Admin | ListInstances, ListPermissionSetsProvisionedToAccount, DescribePermissionSet, ListManagedPoliciesInPermissionSet, ListCustomerManagedPolicyReferencesInPermissionSet, ListAccountAssignments | Read SSO configuration |
| Identity Store | ListUsers | List all SSO users |
| Organizations | ListAccounts, DescribeAccount | List AWS accounts |
| S3 | PutObject | Write CSV files to the bucket |
| CloudWatch Logs | CreateLogGroup, CreateLogStream, PutLogEvents | Lambda logging |

## Notes

- No external dependencies required — uses only `boto3` and Python standard library (both available in Lambda runtime by default)
- The function iterates over all accounts and permission sets, so execution time depends on your organization size
- If you have a large organization (100+ accounts), ensure the 15-minute timeout is sufficient
- CloudWatch Logs will capture detailed progress for debugging

## License

MIT
