# Kubernetes to GCP: EKS and AKS Patterns

## Overview

Both EKS (IRSA) and AKS (Workload Identity) provide pod-level cloud identity without secrets. Combined with GCP WIF, you get fully keyless Kubernetes-to-GCP access across clouds.

## Comparison

| Aspect | EKS (IRSA) | AKS (Workload Identity) |
|--------|-----------|------------------------|
| Identity source | IAM Role via OIDC token | Managed Identity via federated token |
| Token type to GCP | AWS STS SigV4 | OIDC JWT |
| WIF provider type | `create-aws` | `create-oidc` |
| Subject in GCP | AWS ARN | MI Object ID |
| Hub pattern | Assume hub role (cross-account) | Request token for hub app |
| IMDS dependency | None (IRSA bypasses IMDS) | None (projected token) |

## EKS IRSA → Hub Role → GCP WIF

```
EKS Pod (IRSA) → Spoke Role → Assume Hub Role → GCP WIF → GCP SA
```

### ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::<SPOKE>:role/eks-prod-my-app"
```

### Python Auth

```python
import os, boto3
from google.auth import aws as google_aws
from google.auth.transport.requests import Request

def get_gcp_credentials():
    # IRSA creds auto-loaded by boto3
    sts = boto3.client("sts")
    hub = sts.assume_role(
        RoleArn=os.environ["HUB_ROLE_ARN"],
        RoleSessionName="wif",
    )["Credentials"]

    os.environ["AWS_ACCESS_KEY_ID"] = hub["AccessKeyId"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = hub["SecretAccessKey"]
    os.environ["AWS_SESSION_TOKEN"] = hub["SessionToken"]

    creds = google_aws.Credentials.from_info({
        "type": "external_account",
        "audience": os.environ["WIF_AUDIENCE"],
        "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
        "service_account_impersonation_url": f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{os.environ['GCP_SA_EMAIL']}:generateAccessToken",
        "token_url": "https://sts.googleapis.com/v1/token",
        "credential_source": {
            "environment_id": "aws1",
            "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15"
        }
    }, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds
```

## AKS Workload Identity → Entra ID → GCP WIF

```
AKS Pod (Workload Identity) → Entra ID JWT → GCP WIF → GCP SA
```

### ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app
  annotations:
    azure.workload.identity/client-id: "<MI_CLIENT_ID>"
  labels:
    azure.workload.identity/use: "true"
```

### Credential Config (ConfigMap)

```json
{
  "type": "external_account",
  "audience": "//iam.googleapis.com/projects/<NUM>/locations/global/workloadIdentityPools/azure-production/providers/azure-hub",
  "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
  "token_url": "https://sts.googleapis.com/v1/token",
  "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/<SA>@<PROJECT>.iam.gserviceaccount.com:generateAccessToken",
  "credential_source": {
    "url": "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=api://<APP_ID>",
    "headers": {"Metadata": "true"},
    "format": {"type": "json", "subject_token_field_name": "access_token"}
  }
}
```

### Usage

```python
import os
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/app/gcp-credentials.json"
client = storage.Client(project="<PROJECT>")
```

## Troubleshooting

| Symptom | Cloud | Fix |
|---------|-------|-----|
| `AccessDenied` on AssumeRole | AWS | Check hub role trust policy |
| IRSA not injecting tokens | AWS | Verify SA annotation + OIDC provider |
| `AADSTS70021` federated identity error | Azure | Check federated credential subject |
| `Invalid audience` | Azure | Match `--allowed-audiences` with App ID URI |
| `principalSet does not match` | Both | Verify actual identity vs attribute mapping |

## References

- [AWS IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [AKS Workload Identity](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
- [GCP WIF with Kubernetes](https://cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes)
