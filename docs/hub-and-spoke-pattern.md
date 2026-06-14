# Enterprise Hub-and-Spoke Pattern (Multi-Cloud)

## Overview

The Hub-and-Spoke pattern provides a **unified federation architecture** for organizations using both AWS and Azure with GCP. Each cloud has its own "hub" — a dedicated trust anchor registered as the sole provider in the GCP WIF pool.

## Architecture

```
┌─────────────────────────────────────┐    ┌──────────────────────────────────────┐
│       AWS Spoke Accounts            │    │       Azure Spoke Subscriptions       │
│                                     │    │                                       │
│  EKS Pods, Lambda, EC2              │    │  AKS Pods, Functions, VMs             │
│  Each with IRSA / Instance Role     │    │  Each with Managed Identity           │
└──────────────┬──────────────────────┘    └──────────────┬────────────────────────┘
               │ sts:AssumeRole                           │ Get token (audience=Hub App)
               ▼                                          ▼
┌──────────────────────────────────┐    ┌──────────────────────────────────────────┐
│  AWS Hub Account                 │    │  Entra ID Hub App                        │
│  (Dedicated - no workloads)      │    │  (Single app registration)               │
│  One role per workload           │    │  Subject = MI Object ID                  │
└──────────────┬───────────────────┘    └──────────────┬───────────────────────────┘
               │ SigV4                                  │ OIDC JWT
               ▼                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     GCP Workload Identity Federation                              │
│                                                                                  │
│  ┌────────────────────────────┐    ┌────────────────────────────────┐            │
│  │ Pool: aws-{env}            │    │ Pool: azure-{env}              │            │
│  │ Provider: hub-provider     │    │ Provider: azure-hub            │            │
│  │ Type: AWS                  │    │ Type: OIDC                     │            │
│  │ Account: <HUB_ACCOUNT_ID>  │    │ Issuer: sts.windows.net/<TID>/ │            │
│  └─────────────┬──────────────┘    └─────────────┬──────────────────┘            │
│                │                                  │                               │
│                └──────────┬───────────────────────┘                               │
│                           ▼                                                       │
│              GCP Service Accounts (one per workload)                               │
│              Short-lived tokens (1h TTL, auto-refresh)                             │
└───────────────────────────┬───────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     GCP Resources                                                 │
│  BigQuery, Cloud Storage, Pub/Sub, Cloud Run, GKE, Spanner, ...                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| Minimal trust surface | One AWS account + one Entra ID app per environment |
| No secrets anywhere | WIF + IRSA + AKS Workload Identity — zero keys |
| Workload isolation | One GCP SA per workload, minimum privilege |
| Scalable onboarding | New workload = new hub role/MI + SA binding (no pool changes) |
| Centralized audit | Hub account CloudTrail + Entra ID logs + GCP Audit Logs |
| Environment separation | Separate pools per env (prod/staging/dev) |

## Pool and Provider Layout

```
GCP Organization
│
├── Pool: aws-production
│   └── Provider: hub-provider (AWS, account=HUB_PROD)
│       Condition: attribute.aws_role.contains('-prod-')
│
├── Pool: aws-staging
│   └── Provider: hub-provider (AWS, account=HUB_PROD)
│       Condition: attribute.aws_role.contains('-stag-')
│
├── Pool: azure-production
│   └── Provider: azure-hub (OIDC, issuer=sts.windows.net/<TENANT>/)
│       Condition: assertion.tid == '<TENANT_ID>'
│
└── Pool: azure-staging
    └── Provider: azure-hub-stag (OIDC, issuer=sts.windows.net/<TENANT>/)
        Condition: assertion.tid == '<TENANT_ID>'
```

## Onboarding Workflow

### AWS Workload

```bash
# 1. Create hub role (IaC)
aws iam create-role --role-name "<SPOKE_ACCOUNT>-prod-<SERVICE>" \
  --assume-role-policy-document '{"Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::<SPOKE_ACCOUNT>:role/eks-prod-<SERVICE>"},"Action":"sts:AssumeRole"}]}'

# 2. Create GCP SA
gcloud iam service-accounts create <SERVICE>-sa --project=<PROJECT>

# 3. Bind to hub role principal
gcloud iam service-accounts add-iam-policy-binding <SERVICE>-sa@<PROJECT>.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/<NUM>/locations/global/workloadIdentityPools/aws-production/attribute.aws_role/arn:aws:sts::<HUB>:assumed-role/<SPOKE_ACCOUNT>-prod-<SERVICE>"

# 4. Grant GCP roles
gcloud projects add-iam-policy-binding <PROJECT> \
  --role=roles/storage.objectAdmin \
  --member="serviceAccount:<SERVICE>-sa@<PROJECT>.iam.gserviceaccount.com"
```

### Azure Workload

```bash
# 1. Create Managed Identity
az identity create --name <SERVICE>-identity --resource-group <RG>
MI_OID=$(az identity show --name <SERVICE>-identity --resource-group <RG> --query principalId -o tsv)

# 2. Create GCP SA
gcloud iam service-accounts create <SERVICE>-sa --project=<PROJECT>

# 3. Bind to MI Object ID principal
gcloud iam service-accounts add-iam-policy-binding <SERVICE>-sa@<PROJECT>.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principal://iam.googleapis.com/projects/<NUM>/locations/global/workloadIdentityPools/azure-production/subject/${MI_OID}"

# 4. Grant GCP roles
gcloud projects add-iam-policy-binding <PROJECT> \
  --role=roles/bigquery.dataViewer \
  --member="serviceAccount:<SERVICE>-sa@<PROJECT>.iam.gserviceaccount.com"
```

## Security Controls

### AWS Hub Account Hardening

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OnlySTSAndIAM",
      "Effect": "Deny",
      "NotAction": ["sts:*", "iam:*"],
      "Resource": "*"
    },
    {
      "Sid": "RequireMFA",
      "Effect": "Deny",
      "Action": "iam:*",
      "Resource": "*",
      "Condition": {"BoolIfExists": {"aws:MultiFactorAuthPresent": "false"}}
    }
  ]
}
```

### Entra ID Conditional Access

- Require MFA for all admin access to the Hub App
- Restrict sign-in to known IP ranges (if applicable)
- Enable sign-in and audit logs retention (90+ days)

### GCP Organization Policies

```bash
# Force WIF — disable SA key creation org-wide
gcloud org-policies set-policy --organization=<ORG_ID> << EOF
constraint: iam.disableServiceAccountKeyCreation
booleanPolicy:
  enforced: true
EOF
```

## Monitoring

### Unified Dashboard Queries

```bash
# All WIF token exchanges (both AWS and Azure)
gcloud logging read '
  resource.type="audited_resource"
  AND protoPayload.serviceName="sts.googleapis.com"
  AND protoPayload.methodName="google.identity.sts.v1.SecurityTokenService.ExchangeToken"
' --project=<PROJECT> --limit=50 --format=json

# Failed attempts (unauthorized access detection)
gcloud logging read '
  resource.type="audited_resource"
  AND protoPayload.serviceName="sts.googleapis.com"
  AND severity="ERROR"
' --project=<PROJECT> --limit=20
```

### Alert Policies

| Alert | Condition | Severity |
|-------|-----------|----------|
| Unknown AWS account attempting WIF | `account_id != HUB_ACCOUNT` | Critical |
| Unknown Azure tenant attempting WIF | `tid != TENANT_ID` | Critical |
| Token exchange failure spike | > 10 failures in 5 min | High |
| New principal accessing SA | First-time combination | Medium |

## Terraform

See [`terraform/`](../terraform/) for complete modules:
- `terraform/aws-to-gcp/` — AWS Hub-and-Spoke module
- `terraform/azure-to-gcp/` — Azure Hub-and-Spoke module

## References

- [GCP: WIF Best Practices](https://cloud.google.com/iam/docs/best-practices-for-using-workload-identity-federation)
- [AWS: Cross-Account Roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/tutorial_cross-account-with-roles.html)
- [Azure: Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [GCP: Attribute Conditions](https://cloud.google.com/iam/docs/workload-identity-federation#conditions)
