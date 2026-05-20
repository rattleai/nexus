"""ETag middleware for conditional GET requests.

Computes a weak ETag from the response body hash and supports
If-None-Match for 304 Not Modified responses. This saves bandwidth
on mobile networks by avoiding re-downloading unchanged data.
"""

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class ETagMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Only compute ETags for GET responses with content
        if request.method != "GET":
            return response

        # Skip streaming responses (no body attribute)
        if not hasattr(response, "body"):
            return response

        # Skip non-2xx responses
        if response.status_code < 200 or response.status_code >= 300:
            return response

        # Compute weak ETag from body hash
        body = response.body
        if not body:
            return response

        # MD5 is used only for content fingerprinting (weak ETag), never for security.
        etag = f'W/"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'
        response.headers["ETag"] = etag
        response.headers.setdefault("Cache-Control", "private, max-age=0, must-revalidate")

        # Check If-None-Match
        if_none_match = request.headers.get("If-None-Match", "")
        if if_none_match and etag in {t.strip() for t in if_none_match.split(",")}:
            return Response(status_code=304, headers={"ETag": etag})

        return response
