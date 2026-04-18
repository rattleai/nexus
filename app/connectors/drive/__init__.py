"""Provider-specific cloud-drive adapters for RAG ingest.

The generic connector executor (``app.connectors.executor``) is optimized for
JSON-returning tool calls and truncates responses to ``CONNECTOR_MAX_TOOL_OUTPUT_BYTES``.
Binary file downloads need full, untruncated bytes, so cloud-drive ingest goes
through this dedicated adapter layer instead. Adapters reuse the same
``CredentialManager`` + broker machinery so per-tenant encryption, distributed
refresh locking, and per-user confused-deputy protection still apply.
"""

from app.connectors.drive.base import (
    ComposioNotSupportedError,
    DriveAdapter,
    DriveAdapterError,
    DriveFile,
    DriveFileNotFoundError,
    DriveFileTooLargeError,
    DriveItem,
    DriveListing,
    resolve_adapter,
)

__all__ = [
    "DriveAdapter",
    "DriveAdapterError",
    "DriveFile",
    "DriveFileNotFoundError",
    "DriveFileTooLargeError",
    "DriveItem",
    "DriveListing",
    "ComposioNotSupportedError",
    "resolve_adapter",
]
