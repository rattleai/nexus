"""Plugin manifest API endpoint.

Exposes frontend metadata (nav items, feature flags) for all enabled
plugins so the SPA can render dynamic navigation.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.plugins.registry import registry

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("/manifest")
async def get_plugin_manifest():
    """Return merged frontend manifest from all enabled plugins."""
    nav_items: list[dict] = []
    plugins_info: list[dict] = []

    for plugin in registry:
        plugins_info.append(
            {
                "name": plugin.name,
                "displayName": plugin.display_name,
                "version": plugin.version,
            }
        )

        manifest = plugin.get_frontend_manifest()
        if manifest:
            for item in manifest.nav_items:
                nav_items.append(
                    {
                        "href": item.href,
                        "labelKey": item.label_key,
                        "icon": item.icon,
                        "order": item.order,
                        "plugin": plugin.name,
                    }
                )

    nav_items.sort(key=lambda x: x["order"])

    return {
        "plugins": plugins_info,
        "nav_items": nav_items,
    }


@router.get("/health")
async def get_plugin_health():
    """Return health status of all enabled plugins."""
    import asyncio

    results: dict[str, dict] = {}

    async def _check(plugin):  # type: ignore[no-untyped-def]
        try:
            return plugin.name, await asyncio.wait_for(plugin.health_check(), timeout=5.0)
        except TimeoutError:
            return plugin.name, {"status": "unhealthy", "error": "health check timed out"}
        except Exception as exc:
            return plugin.name, {"status": "unhealthy", "error": str(exc)}

    checks = await asyncio.gather(*[_check(p) for p in registry])
    for name, result in checks:
        results[name] = result

    overall = "ok"
    for result in results.values():
        if result.get("status") == "unhealthy":
            overall = "unhealthy"
            break
        if result.get("status") == "degraded":
            overall = "degraded"

    return {"status": overall, "plugins": results}
