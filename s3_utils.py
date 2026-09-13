import logging
import os

import boto3
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

def upload_to_s3(file, filename, folder="uploads", **kwargs):
    filepath = f"{folder}/{secure_filename(filename)}"
    if not BUCKET_NAME:
        logger.warning("S3 bucket is not configured; skipping upload for %s", filepath)
        return None

    stream = getattr(file, "stream", file)
    content_type = getattr(file, "content_type", None) or getattr(stream, "content_type", None) or "application/octet-stream"

    s3.upload_fileobj(
        stream,
        BUCKET_NAME,
        filepath,
        ExtraArgs={
            "ContentType": content_type
        }
    )
    return f"https://{BUCKET_NAME}.s3.amazonaws.com/{filepath}"
