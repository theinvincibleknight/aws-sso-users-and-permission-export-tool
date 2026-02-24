# AWS SSO Permissions Export Tool

Automates the extraction of AWS IAM Identity Center (SSO) user permissions data into CSV/Excel format.

## Prerequisites

1. **AWS CLI configured** with credentials that have access to:
   - IAM Identity Center (SSO Admin)
   - Identity Store
   - AWS Organizations

2. **Python 3.7+** installed

3. **Required IAM Permissions** (in your parent/management account):
   ```
   sso:ListInstances
   sso:DescribePermissionSet
   sso:ListPermissionSets
   sso:ListPermissionSetsProvisionedToAccount
   sso:ListAccountAssignments
   sso:ListManagedPoliciesInPermissionSet
   sso:ListCustomerManagedPolicyReferencesInPermissionSet
   identitystore:ListUsers
   organizations:ListAccounts
   organizations:DescribeAccount
   ```

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Run the script:

**Windows (PowerShell):**
```powershell
python export_sso_permissions.py
```

**Windows (CMD):**
```cmd
python export_sso_permissions.py
```

**Linux/Mac:**
```bash
python3 export_sso_permissions.py
```

### Output Files:
- `AWS_SSO_Users_with_Permissions.csv` - CSV format
- `AWS_SSO_Users_with_Permissions_Export.xlsx` - Excel format

## Output Format

The script generates a file with the following columns:
- **Sr. No** - Serial number
- **User** - Username from Identity Store
- **Account ID** - AWS Account ID
- **Account Name** - AWS Account Name
- **Permission Set** - Permission Set name
- **AWS Managed Policies** - Comma-separated list of AWS managed policies
- **Customer Managed Policies** - Comma-separated list of customer managed policies

## AWS Profile Configuration

If you need to use a specific AWS profile:

```bash
# Set environment variable
export AWS_PROFILE=your-profile-name  # Linux/Mac
$env:AWS_PROFILE="your-profile-name"  # PowerShell

# Or use AWS CLI configure
aws configure --profile your-profile-name
```

## Troubleshooting

### Access Denied Errors
Ensure your AWS credentials have the required permissions listed above. You must run this from the **management/parent account** where IAM Identity Center is configured.

### No SSO Instances Found
Verify that IAM Identity Center is enabled in your AWS account.

### Missing Dependencies
Run: `pip install -r requirements.txt`

## Notes

- The script automatically handles pagination for large datasets
- Groups are not included (only USER principal types)
- Inline policies in permission sets are not captured (only managed policies)
