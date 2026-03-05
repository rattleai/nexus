"""Webhook URL validation — blocks SSRF-prone targets.

Validates that a URL is safe to make outbound HTTP requests to,
rejecting private/internal IP ranges, link-local, loopback, and
cloud metadata endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import structlog

logger = structlog.stdlib.get_logger()

# Well-known cloud metadata endpoints (IP and hostname)
_BLOCKED_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
})


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Can't parse — block to be safe

    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_webhook_url(url: str) -> str | None:
    """Validate a webhook URL is safe to call.

    Returns None if the URL is safe, or an error message string if it should be rejected.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    # Must be HTTPS or HTTP
    if parsed.scheme not in ("http", "https"):
        return "Webhook URL must use http or https"

    # Must have a host
    hostname = parsed.hostname
    if not hostname:
        return "Webhook URL must have a hostname"

    # Block well-known metadata endpoints
    if hostname.lower() in _BLOCKED_HOSTS:
        return "Webhook URL points to a blocked host"

    # Resolve hostname and check all resulting IPs.
    # Uses synchronous resolution — this is called from both sync (Celery)
    # and async (FastAPI) contexts. The previous async implementation used
    # run_until_complete() inside a running loop, which raises RuntimeError.
    try:
        results = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "Could not resolve webhook URL hostname"

    for _family, _, _, _, sockaddr in results:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            logger.warning(
                "webhook_ssrf_blocked",
                url=url,
                resolved_ip=ip_str,
                hostname=hostname,
            )
            return "Webhook URL must not resolve to a private or internal IP address"

    return None
