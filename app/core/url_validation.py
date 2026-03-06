"""Webhook URL validation — blocks SSRF-prone targets.

Validates that a URL is safe to make outbound HTTP requests to,
rejecting private/internal IP ranges, link-local, loopback, and
cloud metadata endpoints.

Provides both sync (for Celery) and async (for FastAPI) variants.
"""

import asyncio
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
    "fd00:ec2::254",          # AWS IMDSv2 IPv6 endpoint
})


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range.

    Handles IPv6-mapped IPv4 addresses (e.g., ::ffff:127.0.0.1) by extracting
    the underlying IPv4 address and checking it separately.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Can't parse — block to be safe

    # Check IPv6-mapped IPv4 addresses (e.g., ::ffff:10.0.0.1)
    # These can bypass is_private checks in some Python versions.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped

    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _check_parsed_url(url: str) -> tuple[str | None, str | None, int | None]:
    """Parse and validate URL structure. Returns (error, hostname, port)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format", None, None

    if parsed.scheme not in ("http", "https"):
        return "Webhook URL must use http or https", None, None

    hostname = parsed.hostname
    if not hostname:
        return "Webhook URL must have a hostname", None, None

    if hostname.lower() in _BLOCKED_HOSTS:
        return "Webhook URL points to a blocked host", None, None

    return None, hostname, parsed.port


def _check_resolved_ips(url: str, hostname: str, results: list) -> str | None:
    """Check resolved IPs for private addresses. Returns error or None."""
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


def validate_webhook_url(url: str) -> str | None:
    """Validate a webhook URL is safe to call (synchronous).

    Returns None if the URL is safe, or an error message string if it should be rejected.
    Used in Celery worker (sync) contexts.
    """
    error, hostname, port = _check_parsed_url(url)
    if error:
        return error

    try:
        results = socket.getaddrinfo(hostname, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "Could not resolve webhook URL hostname"

    return _check_resolved_ips(url, hostname, results)


async def validate_webhook_url_async(url: str) -> str | None:
    """Validate a webhook URL is safe to call (async, non-blocking).

    Returns None if the URL is safe, or an error message string if it should be rejected.
    Used in FastAPI (async) contexts to avoid blocking the event loop.
    """
    error, hostname, port = _check_parsed_url(url)
    if error:
        return error

    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(hostname, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "Could not resolve webhook URL hostname"

    return _check_resolved_ips(url, hostname, results)
