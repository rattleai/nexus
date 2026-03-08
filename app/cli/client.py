"""HTTP client wrapper for the CADPrice CLI.

Thin wrapper around httpx.Client that handles authentication,
error formatting, and consistent output.
"""

from __future__ import annotations

import httpx

from app import __version__


class CLIError(Exception):
    """Raised for CLI-level errors with exit code context."""

    def __init__(self, message: str, exit_code: int = 1, hint: str | None = None):
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        super().__init__(message)


class CadpriceClient:
    """HTTP client for interacting with the CADPrice REST API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "X-API-Key": api_key,
                "User-Agent": f"cadprice-cli/{__version__}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
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

        Raises CLIError on failure with hint if available.
        """
        headers = {}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        try:
            response = self._client.request(
                method,
                path,
                json=json,
                params=params,
                headers=headers,
            )
        except httpx.ConnectError as exc:
            raise CLIError(
                f"Cannot connect to {self.base_url}",
                exit_code=2,
                hint="Is the CADPrice API server running? Check CADPRICE_BASE_URL.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CLIError("Request timed out", exit_code=2) from exc

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
