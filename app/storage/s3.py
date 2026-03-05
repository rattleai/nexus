import asyncio
import threading

import boto3
import structlog
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import settings

logger = structlog.stdlib.get_logger()

_s3_client = None
_s3_lock = threading.Lock()


def get_s3_client():
    """Return a reusable boto3 S3 client configured for S3-compatible storage.

    Thread-safe via double-checked locking.
    """
    global _s3_client
    if _s3_client is None:
        with _s3_lock:
            if _s3_client is None:
                if not settings.storage_configured:
                    raise RuntimeError(
                        "S3 storage is not configured. Set S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, "
                        "and S3_SECRET_ACCESS_KEY environment variables."
                    )
                _s3_client = boto3.client(
                    "s3",
                    endpoint_url=settings.S3_ENDPOINT_URL,
                    aws_access_key_id=settings.S3_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                    region_name=settings.S3_REGION,
                    config=Config(
                        signature_version="s3v4",
                        connect_timeout=5,
                        read_timeout=30,
                        retries={"max_attempts": 2},
                    ),
                )
    return _s3_client


class StorageError(Exception):
    """Raised when a storage operation fails."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class S3Storage:
    """S3-compatible object storage with proper error handling."""

    def __init__(self) -> None:
        self._client = get_s3_client()
        self._bucket = settings.S3_BUCKET

    # ── sync interface (Celery workers) ──────────────────────

    def upload(self, key: str, data: bytes) -> None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("s3_upload_failed", key=key, error_code=error_code, error=str(exc))
            raise StorageError(f"Upload failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_upload_failed", key=key, error=str(exc))
            raise StorageError("Upload failed: storage service unavailable") from exc

    def download(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "NoSuchKey":
                raise StorageError("File not found in storage", status_code=404) from exc
            logger.error("s3_download_failed", key=key, error_code=error_code, error=str(exc))
            raise StorageError(f"Download failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_download_failed", key=key, error=str(exc))
            raise StorageError("Download failed: storage service unavailable") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("404", "NoSuchKey"):
                return False
            logger.error("s3_head_failed", key=key, error_code=error_code)
            raise StorageError(f"Storage check failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_head_failed", key=key, error=str(exc))
            raise StorageError("Storage check failed: service unavailable") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            logger.error("s3_delete_failed", key=key, error=str(exc))
            raise StorageError("Delete failed: storage error") from exc

    # ── async interface (FastAPI handlers) ───────────────────

    async def async_upload(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self.upload, key, data)

    async def async_download(self, key: str) -> bytes:
        return await asyncio.to_thread(self.download, key)

    async def async_exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.exists, key)

    async def async_delete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)


def handle_storage_error(exc: StorageError) -> HTTPException:
    """Convert a StorageError into an appropriate HTTPException."""
    return HTTPException(status_code=exc.status_code, detail=str(exc))
