"""Composio credential broker (P2.2).

Delegates OAuth, token rotation, rate limiting, and tool execution to
Composio's managed platform. Tokens live in Composio's vault and never
enter the agent runtime — a meaningful compliance + blast-radius win.

Composio identifies connections by ``entity_id``. We scope entities as
``tenant:{tenant_id}:user:{actor_user_id}`` so per-user confused-deputy
prevention is baked into the identifier itself.

If the ``composio-core`` SDK is not installed or no ``COMPOSIO_API_KEY``
is configured, ``is_available()`` returns False and the broker router
falls back to the in-house broker transparently. This lets teams adopt
Composio incrementally without forcing a hard dependency.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.brokers.base import (
    AuthorizationStart,
    CredentialBroker,
    ToolDescriptor,
    ToolResult,
)
from app.connectors.models import (
    ConnectionStatus,
    ConnectorDefinition,
    TenantConnection,
)

logger = structlog.stdlib.get_logger()


def _entity_id(tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None) -> str:
    """Build the Composio entity_id for a tenant + user."""
    user_part = str(actor_user_id) if actor_user_id else "system"
    return f"tenant:{tenant_id}:user:{user_part}"


class ComposioBroker(CredentialBroker):
    """Composio-backed credential broker.

    Lazy-imports ``composio_core`` so the platform still starts when it
    isn't installed.
    """

    name = "composio"

    def __init__(self) -> None:
        self._client: Any | None = None
        self._available = False
        self._attempted = False

    def _ensure_client(self) -> Any | None:
        """Import composio-core and build a client if configured."""
        if self._attempted:
            return self._client

        self._attempted = True
        if not settings.COMPOSIO_API_KEY:
            logger.info("composio_broker_disabled_no_api_key")
            return None

        try:
            from composio import Composio  # type: ignore
        except Exception as exc:
            logger.info(
                "composio_sdk_not_installed",
                error=str(exc)[:200],
            )
            return None

        try:
            self._client = Composio(
                api_key=settings.COMPOSIO_API_KEY,
                base_url=settings.COMPOSIO_BASE_URL,
            )
            self._available = True
            logger.info("composio_broker_initialized")
        except Exception:
            logger.warning("composio_broker_init_failed", exc_info=True)
            self._client = None

        return self._client

    def is_available(self) -> bool:
        self._ensure_client()
        return self._available

    async def start_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AuthorizationStart:
        client = self._ensure_client()
        if client is None:
            raise RuntimeError(
                "Composio broker is not available. Install composio-core and "
                "set COMPOSIO_API_KEY."
            )

        entity = _entity_id(tenant_id, actor_user_id)
        # Composio SDK call surface has shifted across versions; use the
        # stable connected_accounts.initiate interface.
        try:
            conn_request = await _call_async(
                client.connected_accounts.initiate,
                entity_id=entity,
                app_name=connector_def.slug,
                redirect_uri=redirect_uri,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Composio authorization initiate failed: {str(exc)[:200]}"
            ) from exc

        return AuthorizationStart(
            auth_url=getattr(conn_request, "redirect_url", ""),
            state=str(getattr(conn_request, "id", "")),
        )

    async def complete_authorization(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        code: str,
        state: str,
        redirect_uri: str,
        db: AsyncSession,
    ) -> TenantConnection:
        """Composio handles the OAuth callback internally — we just record
        the resulting connection in our own ``tenant_connections`` table
        so the UI can list it.
        """
        client = self._ensure_client()
        if client is None:
            raise RuntimeError("Composio broker is not available")

        connection = TenantConnection(
            tenant_id=tenant_id,
            connector_definition_id=connector_def.id,
            display_name=connector_def.name,
            status=ConnectionStatus.ACTIVE,
            mcp_session_id=state,  # Composio connected-account id
        )
        db.add(connection)
        await db.flush()
        logger.info(
            "composio_connection_recorded",
            composio_id=state,
            connector=connector_def.slug,
        )
        return connection

    async def list_tools(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> list[ToolDescriptor]:
        client = self._ensure_client()
        if client is None:
            return []

        entity = _entity_id(tenant_id, actor_user_id)
        try:
            result = await _call_async(
                client.tools.get, entity_id=entity, app=connector_def.slug,
            )
        except Exception:
            logger.debug("composio_tools_fetch_failed", exc_info=True)
            return []

        descriptors: list[ToolDescriptor] = []
        for tool in result or []:
            name = getattr(tool, "name", None) or tool.get("name", "")  # type: ignore
            if not name:
                continue
            description = (
                getattr(tool, "description", None)
                or tool.get("description", "")  # type: ignore
                or ""
            )
            schema = (
                getattr(tool, "parameters", None)
                or tool.get("parameters", {})  # type: ignore
                or {}
            )
            descriptors.append(
                ToolDescriptor(
                    name=f"connector:{connector_def.slug}:{name}",
                    description=description,
                    input_schema=schema,
                    trust_level=connector_def.trust_level.value,
                )
            )
        return descriptors

    async def invoke_tool(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        actor_user_id: uuid.UUID | None = None,
        agent_instance_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        client = self._ensure_client()
        if client is None:
            return {
                "error": "Composio broker is not available",
                "is_error": True,
            }

        entity = _entity_id(tenant_id, actor_user_id)

        try:
            result = await _call_async(
                client.actions.execute,
                action=tool_name,
                params=arguments,
                entity_id=entity,
            )
        except Exception as exc:
            logger.warning(
                "composio_invoke_failed",
                connector=connector_def.slug,
                tool=tool_name,
                error=str(exc)[:200],
            )
            return {
                "error": f"Composio tool '{tool_name}' failed: {str(exc)[:200]}",
                "is_error": True,
            }

        successful = getattr(result, "successful", True)
        data = getattr(result, "data", None)
        if data is None and isinstance(result, dict):
            successful = result.get("successful", True)
            data = result.get("data")

        return {
            "content": data if data is not None else "",
            "is_error": not successful,
        }

    async def revoke_connection(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        client = self._ensure_client()
        if client is None:
            return
        composio_id = connection.mcp_session_id
        if not composio_id:
            return
        try:
            await _call_async(client.connected_accounts.delete, id=composio_id)
        except Exception:
            logger.debug("composio_revoke_failed", exc_info=True)


async def _call_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a function that may be sync or async and return its result."""
    import inspect

    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


composio_broker = ComposioBroker()
