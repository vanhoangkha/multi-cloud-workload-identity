"""AWS WIF auth: IRSA → Hub Role → GCP WIF → GCS client."""
import os, logging, boto3
from google.auth import aws as google_aws
from google.auth.transport.requests import Request
from google.cloud import storage

logger = logging.getLogger(__name__)

def get_gcs_client() -> storage.Client:
    sts = boto3.client("sts", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    hub = sts.assume_role(
        RoleArn=os.environ["HUB_ROLE_ARN"],
        RoleSessionName="wif-session",
        DurationSeconds=3600,
    )["Credentials"]
    logger.info("Assumed hub role: %s", os.environ["HUB_ROLE_ARN"])

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
    logger.info("GCP WIF token obtained for: %s", os.environ["GCP_SA_EMAIL"])
    return storage.Client(credentials=creds, project=os.environ["GCP_PROJECT_ID"])
