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
