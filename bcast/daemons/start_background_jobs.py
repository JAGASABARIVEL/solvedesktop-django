import os
import threading
import time
import signal
import sys
import logging
import mimetypes
import psycopg2
from datetime import datetime, timedelta
import boto3
from botocore.client import Config
from decouple import config

os.environ["PG_DB"] = config("PG_DB")
os.environ["PG_HOST"] = config("PG_HOST")
os.environ["PG_PORT"] = config("PG_PORT")
os.environ["PG_USER"] = config("PG_USER")
os.environ["PG_PASSWORD"] = config("PG_PASSWORD")
os.environ["B2_ENDPOINT_URL"] = config("B2_ENDPOINT_URL")
os.environ["B2_ACCESS_KEY_ID"] = config("B2_ACCESS_KEY_ID")
os.environ["B2_SECRET_ACCESS_KEY"] = config("B2_SECRET_ACCESS_KEY")
os.environ["B2_STORAGE_BUCKET_NAME"] = config("B2_STORAGE_BUCKET_NAME")

# =========================
# Setup logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("background_service.log", mode="a")
    ]
)

# =========================
# Presigned URL generator
# =========================
def generate_presigned_url(object_key, expiry_seconds=3600):
    content_type, _ = mimetypes.guess_type(object_key)
    if content_type is None:
        content_type = 'application/octet-stream'

    s3_client = boto3.client(
        's3',
        endpoint_url=os.environ["B2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["B2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["B2_SECRET_ACCESS_KEY"],
        config=Config(signature_version='s3v4'),
        region_name='us-west-002'
    )

    return s3_client.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': os.environ["B2_STORAGE_BUCKET_NAME"],
            'Key': object_key,
            'ResponseContentDisposition': 'inline',
            'ResponseContentType': content_type,
        },
        ExpiresIn=expiry_seconds
    )

# =========================
# Database connection helper
# =========================
def get_connection():
    return psycopg2.connect(
        dbname=os.environ["PG_DB"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
    )

# =========================
# Refresh Signed URLs Worker
# =========================
def refresh_signed_urls(expiry_seconds=3600, interval=1800):
    logging.info("Started refresh_signed_urls thread")
    while True:
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # 1. Fetch expired files
            cursor.execute("""
                SELECT id, s3_key
                FROM manage_files_file
                WHERE signed_url_expires_at < NOW();
            """)
            expired_files = cursor.fetchall()

            if expired_files:
                logging.info(f"Refreshing {len(expired_files)} expired files")

            # 2. Refresh URLs
            new_expiry_time = datetime.utcnow() + timedelta(seconds=expiry_seconds)
            for file_id, s3_key in expired_files:
                try:
                    new_url = generate_presigned_url(s3_key, expiry_seconds)
                    cursor.execute("""
                        UPDATE manage_files_file
                        SET signed_url = %s,
                            signed_url_expires_at = %s
                        WHERE id = %s;
                    """, (new_url, new_expiry_time, file_id))
                except Exception as e:
                    logging.error(f"Failed refreshing file {file_id}: {e}")

            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logging.error(f"DB/Worker error: {e}")

        time.sleep(interval)  # wait before next run

# =========================
# Graceful shutdown handler
# =========================
def shutdown_service(signum, frame):
    logging.info("Shutting down background service...")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_service)
signal.signal(signal.SIGTERM, shutdown_service)

# =========================
# Service Entrypoint
# =========================
def main():
    logging.info("Starting background service")

    # Add threads here
    threads = [
        threading.Thread(target=refresh_signed_urls, args=(3600, 1800), daemon=True, name="PresignedURLRefresher")
    ]

    for t in threads:
        t.start()

    # Keep main thread alive
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()

