"""CPQ-specific exception hierarchy.

These exceptions are registered with the plugin error handler system
so they produce clean, domain-specific error responses.
"""

from __future__ import annotations


class CPQError(Exception):
    """Base exception for all CPQ errors."""

    code: str = "CPQ_ERROR"
    http_status: int = 400

    def __init__(self, detail: str = "Configuration error", **extra: object):
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class ConfigurationValidationError(CPQError):
    """A configuration violates business rules or constraints."""

    code = "INVALID_CONFIGURATION"
    http_status = 422


class ConfigurationConflictError(CPQError):
    """Constraint propagation detected a contradiction."""

    code = "CONFIGURATION_CONFLICT"
    http_status = 409


class ProductNotFoundError(CPQError):
    """Referenced product does not exist or is not accessible."""

    code = "PRODUCT_NOT_FOUND"
    http_status = 404


class VariantExplosionError(CPQError):
    """Too many variant combinations would be generated."""

    code = "VARIANT_EXPLOSION"
    http_status = 413
