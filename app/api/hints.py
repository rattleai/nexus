"""Agent-friendly error hint registry.

Maps (status_code, error_code) tuples to hint template strings that provide
actionable guidance for AI agents. Templates can include {field} placeholders
filled from the error context.
"""

from __future__ import annotations

# Registry: (status_code, error_code_prefix) -> hint template
# Error codes are matched by prefix so "HTTP_401" matches "HTTP_4*"
HINT_REGISTRY: dict[tuple[int, str], str] = {
    # Authentication
    (401, "HTTP_401"): (
        "Check that the X-API-Key header contains a valid, non-revoked API key. Create one via POST /api/v1/api-keys."
    ),
    # Authorization
    (403, "HTTP_403"): (
        "The API key lacks the required scopes for this operation. "
        "Check the key's scopes via GET /api/v1/api-keys and ensure it has the necessary permissions."
    ),
    # Insufficient balance
    (402, "HTTP_402"): ("Insufficient wallet balance. Top up via POST /api/v1/ai/wallet/topup before retrying."),
    # Not found
    (404, "HTTP_404"): ("The requested resource was not found. Verify the ID or path is correct."),
    # Validation error
    (422, "VALIDATION_ERROR"): (
        "Request validation failed. Check the 'errors' array for field-specific details. "
        "For model names, use GET /api/v1/ai/models to list valid options."
    ),
    # Rate limiting
    (429, "HTTP_429"): (
        "Rate limit exceeded. Wait for the duration specified in the Retry-After header "
        "before retrying. Use X-Idempotency-Key for safe retries on mutating endpoints."
    ),
    # Conflict
    (409, "HTTP_409"): (
        "A resource with the same identifier already exists. Use a unique name or check existing resources first."
    ),
    # Provider error
    (502, "HTTP_502"): (
        "The upstream AI provider is temporarily unavailable. Retry after a brief delay or try a different model."
    ),
    # Internal error
    (500, "INTERNAL_ERROR"): ("An unexpected error occurred. Include the request_id when reporting this issue."),
}


def get_hint(status_code: int, error_code: str) -> str | None:
    """Look up a hint for the given status code and error code.

    Tries exact match first, then falls back to (status_code, "HTTP_{status}") pattern.
    Returns None if no hint is found.
    """
    # Exact match
    hint = HINT_REGISTRY.get((status_code, error_code))
    if hint:
        return hint

    # Fallback to HTTP_xxx pattern
    generic_code = f"HTTP_{status_code}"
    return HINT_REGISTRY.get((status_code, generic_code))
