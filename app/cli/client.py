"""HTTP client wrapper for the NEXUS CLI.

Thin wrapper around httpx.Client that handles authentication,
error formatting, retries with exponential backoff, and consistent output.
"""

from __future__ import annotations

import time

import httpx

from app import __version__
from app.cli.branding import BASE_URL_ENV, CLI_NAME

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds
_RETRYABLE_STATUS_CODES = {502, 503, 504}


class CLIError(Exception):
    """Raised for CLI-level errors with exit code context."""

    def __init__(self, message: str, exit_code: int = 1, hint: str | None = None):
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        super().__init__(message)


class NexusClient:
    """HTTP client for interacting with the NEXUS REST API."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "X-API-Key": api_key,
                "User-Agent": f"{CLI_NAME}-cli/{__version__}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Make an API request and return the parsed response.

        Retries transient network errors and 502/503/504 responses with
        exponential backoff. Raises CLIError on failure with hint if available.
        """
        headers = {}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )
            except httpx.ConnectError as exc:
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF_BASE * (2**attempt))
                    continue
                raise CLIError(
                    f"Cannot connect to {self.base_url}",
                    exit_code=2,
                    hint=f"Is the API server running? Check {BASE_URL_ENV}.",
                ) from exc
            except httpx.TimeoutException as exc:
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF_BASE * (2**attempt))
                    continue
                raise CLIError("Request timed out", exit_code=2) from exc

            # Retry on transient server errors
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_BASE * (2**attempt))
                continue

            break

        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = {"detail": response.text}

            detail = data.get("detail", "Unknown error")
            hint = data.get("hint")
            exit_code = 1 if response.status_code < 500 else 2

            raise CLIError(
                f"HTTP {response.status_code}: {detail}",
                exit_code=exit_code,
                hint=hint,
            )

        if response.status_code == 204:
            return {"status": "ok"}

        return response.json()

    def get(self, path: str, **kwargs) -> dict:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> dict:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> dict:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> dict:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()
