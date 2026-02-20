import asyncio

import boto3
from botocore.client import Config

from cadprice.config import settings

_s3_client = None


def get_s3_client():
    """Return a reusable boto3 S3 client configured for Cloudflare R2."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


class S3Storage:
    """S3-compatible object storage (Cloudflare R2)."""

    def __init__(self) -> None:
        self._client = get_s3_client()
        self._bucket = settings.S3_BUCKET

    # ── sync interface (Celery workers) ──────────────────────

    def upload(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def download(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._client.exceptions.ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    # ── async interface (FastAPI handlers) ───────────────────

    async def async_upload(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self.upload, key, data)

    async def async_download(self, key: str) -> bytes:
        return await asyncio.to_thread(self.download, key)

    async def async_exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.exists, key)

    async def async_delete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)
