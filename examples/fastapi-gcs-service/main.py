"""Multi-cloud GCS service — supports both AWS and Azure WIF auth."""
import os, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from google.cloud import storage
from google.api_core.exceptions import NotFound, Forbidden

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ["GCS_BUCKET"]
CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws")  # "aws" or "azure"
_gcs: storage.Client | None = None


def _init_client():
    if CLOUD_PROVIDER == "aws":
        from auth_aws import get_gcs_client
        return get_gcs_client()
    else:
        # Azure: uses GOOGLE_APPLICATION_CREDENTIALS with credential config
        return storage.Client(project=os.environ["GCP_PROJECT_ID"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gcs
    logger.info("Init GCS client via %s WIF...", CLOUD_PROVIDER)
    _gcs = _init_client()
    logger.info("Ready. bucket=%s", GCS_BUCKET)
    yield
    _gcs = None

app = FastAPI(title="multi-cloud-gcs-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "provider": CLOUD_PROVIDER}


@app.get("/objects")
def list_objects(prefix: str = "", max_results: int = 100):
    blobs = _gcs.list_blobs(GCS_BUCKET, prefix=prefix, max_results=max_results)
    return {"objects": [b.name for b in blobs]}


@app.get("/objects/{path:path}")
def download_object(path: str):
    blob = _gcs.bucket(GCS_BUCKET).blob(path)
    try:
        data = blob.download_as_bytes()
    except NotFound:
        raise HTTPException(404, f"{path} not found")
    except Forbidden:
        raise HTTPException(403, "Access denied")
    from fastapi.responses import StreamingResponse
    return StreamingResponse(iter([data]), media_type=blob.content_type or "application/octet-stream")
