import os
import boto3
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

def upload_to_s3(file, filename, folder="uploads"):
    filepath = f"{folder}/{secure_filename(filename)}"
    s3.upload_fileobj(
        file,
        BUCKET_NAME,
        filepath,
        ExtraArgs={
            "ContentType": file.content_type
        }
    )
    return f"https://{BUCKET_NAME}.s3.amazonaws.com/{filepath}"
