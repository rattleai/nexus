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


def _validate_key(key: str) -> str:
    """Sanitize and validate an S3 object key to prevent path traversal."""
    from urllib.parse import unquote

    # Decode percent-encoded characters first to catch %2e%2e → ..
    normalized = unquote(key)
    # Normalize path separators
    normalized = normalized.replace("\\", "/")
    # Reject any traversal attempts (check both encoded and decoded forms)
    if ".." in normalized or normalized.startswith("/"):
        raise StorageError("Invalid storage key", status_code=400)
    # Strip leading/trailing whitespace
    normalized = normalized.strip()
    if not normalized:
        raise StorageError("Storage key cannot be empty", status_code=400)
    return normalized


class S3Storage:
    """S3-compatible object storage with proper error handling."""

    def __init__(self) -> None:
        self._client = get_s3_client()
        self._bucket = settings.S3_BUCKET

    # ── sync interface (Celery workers) ──────────────────────

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        key = _validate_key(key)
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("s3_upload_failed", key=key, error_code=error_code, error=str(exc))
            raise StorageError(f"Upload failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_upload_failed", key=key, error=str(exc))
            raise StorageError("Upload failed: storage service unavailable") from exc

    def download(self, key: str) -> bytes:
        key = _validate_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()
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
        key = _validate_key(key)
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
        key = _validate_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            logger.error("s3_delete_failed", key=key, error=str(exc))
            raise StorageError("Delete failed: storage error") from exc

    def upload_fileobj(self, key: str, file_obj, max_size: int) -> int:
        """Upload a file-like object to S3 using multipart upload.

        Streams data in chunks to avoid loading entire file into memory.
        Enforces max_size limit during upload, aborting if exceeded.
        Returns the total number of bytes uploaded.
        """
        key = _validate_key(key)
        chunk_size = 5 * 1024 * 1024  # 5 MB (S3 minimum part size for multipart)
        total_size = 0

        try:
            # Read first chunk to determine if we need multipart
            first_chunk = file_obj.read(chunk_size)
            if not first_chunk:
                self._client.put_object(Bucket=self._bucket, Key=key, Body=b"")
                return 0

            total_size = len(first_chunk)
            if total_size > max_size:
                raise StorageError(f"File too large (max {max_size // (1024 * 1024)} MB)", status_code=413)

            # Check if there's more data
            next_chunk = file_obj.read(chunk_size)
            if not next_chunk:
                # Small file — use simple put_object
                self._client.put_object(Bucket=self._bucket, Key=key, Body=first_chunk)
                return total_size

            # Large file — use multipart upload
            mpu = self._client.create_multipart_upload(Bucket=self._bucket, Key=key)
            upload_id = mpu["UploadId"]
            parts = []
            part_number = 1

            try:
                # Upload first chunk as part 1
                part = self._client.upload_part(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=first_chunk,
                )
                parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                part_number += 1

                # Upload remaining chunks
                chunk = next_chunk
                while chunk:
                    total_size += len(chunk)
                    if total_size > max_size:
                        raise StorageError(f"File too large (max {max_size // (1024 * 1024)} MB)", status_code=413)

                    part = self._client.upload_part(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=chunk,
                    )
                    parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                    part_number += 1
                    chunk = file_obj.read(chunk_size)

                self._client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                self._client.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
                raise

            return total_size

        except StorageError:
            raise
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("s3_streaming_upload_failed", key=key, error_code=error_code)
            raise StorageError(f"Upload failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_streaming_upload_failed", key=key, error=str(exc))
            raise StorageError("Upload failed: storage service unavailable") from exc

    def list_objects(self, prefix: str) -> list[str]:
        """List object keys under the given prefix with pagination."""
        prefix = _validate_key(prefix)
        keys: list[str] = []
        try:
            kwargs = {"Bucket": self._bucket, "Prefix": prefix}
            while True:
                response = self._client.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    keys.append(obj["Key"])
                if not response.get("IsTruncated"):
                    break
                kwargs["ContinuationToken"] = response["NextContinuationToken"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("s3_list_failed", prefix=prefix, error_code=error_code)
            raise StorageError(f"List failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_list_failed", prefix=prefix, error=str(exc))
            raise StorageError("List failed: storage service unavailable") from exc
        return keys

    def generate_presigned_url(
        self,
        key: str,
        *,
        expiry_seconds: int = 3600,
        content_type: str | None = None,
        method: str = "get_object",
    ) -> str:
        """Generate a presigned URL for temporary direct access to an S3 object.

        Args:
            key: The S3 object key.
            expiry_seconds: URL validity duration (default 1 hour, max 7 days).
            content_type: Optional content type for upload URLs.
            method: S3 operation — "get_object" for downloads, "put_object" for uploads.

        Returns:
            A presigned URL string.
        """
        key = _validate_key(key)
        expiry_seconds = min(expiry_seconds, 604800)  # Cap at 7 days

        params: dict = {"Bucket": self._bucket, "Key": key}
        if content_type and method == "put_object":
            params["ContentType"] = content_type

        try:
            return self._client.generate_presigned_url(
                method,
                Params=params,
                ExpiresIn=expiry_seconds,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("s3_presigned_url_failed", key=key, error=str(exc))
            raise StorageError("Failed to generate presigned URL") from exc

    async def async_generate_presigned_url(
        self,
        key: str,
        *,
        expiry_seconds: int = 3600,
        content_type: str | None = None,
        method: str = "get_object",
    ) -> str:
        return await asyncio.to_thread(
            self.generate_presigned_url,
            key,
            expiry_seconds=expiry_seconds,
            content_type=content_type,
            method=method,
        )

    # ── async interface (FastAPI handlers) ───────────────────

    async def async_upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await asyncio.to_thread(self.upload, key, data, content_type)

    async def async_upload_fileobj(self, key: str, file_obj, max_size: int) -> int:
        """Stream a file-like object to S3 without loading into memory."""
        return await asyncio.to_thread(self.upload_fileobj, key, file_obj, max_size)

    async def async_download(self, key: str) -> bytes:
        return await asyncio.to_thread(self.download, key)

    async def async_exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.exists, key)

    async def async_delete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    async def async_list_objects(self, prefix: str) -> list[str]:
        return await asyncio.to_thread(self.list_objects, prefix)

    def list_objects_detailed(self, prefix: str) -> list[dict]:
        """List objects under prefix with size and last-modified metadata."""
        prefix = _validate_key(prefix)
        items: list[dict] = []
        try:
            kwargs = {"Bucket": self._bucket, "Prefix": prefix}
            while True:
                response = self._client.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    items.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"],
                        }
                    )
                if not response.get("IsTruncated"):
                    break
                kwargs["ContinuationToken"] = response["NextContinuationToken"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error("s3_list_failed", prefix=prefix, error_code=error_code)
            raise StorageError(f"List failed: {error_code}") from exc
        except BotoCoreError as exc:
            logger.error("s3_list_failed", prefix=prefix, error=str(exc))
            raise StorageError("List failed: storage service unavailable") from exc
        return items

    async def async_list_objects_detailed(self, prefix: str) -> list[dict]:
        return await asyncio.to_thread(self.list_objects_detailed, prefix)


def handle_storage_error(exc: StorageError) -> HTTPException:
    """Convert a StorageError into an appropriate HTTPException.

    Returns a safe error message without leaking S3 error codes or
    infrastructure details.
    """
    _SAFE_MESSAGES = {
        400: "Invalid storage request",
        404: "File not found",
        413: str(exc) if "too large" in str(exc).lower() else "File too large",
        502: "Storage service error",
    }
    detail = _SAFE_MESSAGES.get(exc.status_code, "Storage operation failed")
    return HTTPException(status_code=exc.status_code, detail=detail)
