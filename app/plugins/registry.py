"""Plugin discovery and registration.

Discovery strategy:
1. Scan ``app/apps/*/`` for packages containing a ``plugin.py`` with a
   module-level ``PLUGIN`` attribute that is an ``AppPluginBase`` instance.
2. Check each discovered plugin's ``feature_flag`` env var — enabled by
   default (truthy or absent).
3. Register enabled plugins in a singleton ``PluginRegistry``.

The registry is populated once at import time via ``discover_plugins()``,
which must be called before ``create_app()``.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import structlog

from app.plugins.base import AppPluginBase

logger = structlog.stdlib.get_logger()

_APPS_DIR = Path(__file__).resolve().parent.parent / "apps"


class PluginRegistry:
    """Holds all discovered and enabled app plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, AppPluginBase] = {}

    @property
    def plugins(self) -> dict[str, AppPluginBase]:
        return dict(self._plugins)

    def register(self, plugin: AppPluginBase) -> None:
        existing = self._plugins.get(plugin.name)
        if existing is not None:
            # Idempotent re-registration of the same plugin is a no-op:
            # both `app.main` and the alembic env import-time hook call
            # `discover_plugins()`, and any consumer that imports both
            # would otherwise raise. We only fail when the SAME name is
            # backed by a *different* plugin object (genuine collision).
            if existing is plugin or type(existing) is type(plugin):
                logger.debug("plugin_already_registered", name=plugin.name)
                return
            raise ValueError(
                f"Duplicate plugin name '{plugin.name}': "
                f"already registered by {type(existing).__name__}, "
                f"now attempted by {type(plugin).__name__}."
            )
        self._plugins[plugin.name] = plugin
        logger.info(
            "plugin_registered",
            name=plugin.name,
            version=plugin.version,
            display_name=plugin.display_name,
        )

    def get(self, name: str) -> AppPluginBase | None:
        return self._plugins.get(name)

    def __iter__(self) -> Iterator[AppPluginBase]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def __bool__(self) -> bool:
        return bool(self._plugins)


# Module-level singleton
registry = PluginRegistry()


def discover_plugins() -> PluginRegistry:
    """Scan ``app/apps/*/`` for plugin packages and register enabled ones.

    Each app package must have a ``plugin.py`` module with a module-level
    ``PLUGIN`` attribute that is an instance of ``AppPluginBase``.

    A plugin is registered when its ``feature_flag`` env var is absent
    (opt-in by default) or set to a truthy value (``1``, ``true``, ``yes``).
    """
    if not _APPS_DIR.is_dir():
        logger.info("plugin_discovery_no_apps_dir", path=str(_APPS_DIR))
        return registry

    for entry in sorted(_APPS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "__init__.py").exists():
            continue
        if not (entry / "plugin.py").exists():
            logger.debug("plugin_discovery_skip_no_plugin_py", app=entry.name)
            continue

        try:
            module = importlib.import_module(f"app.apps.{entry.name}.plugin")
        except Exception:
            logger.error("plugin_discovery_import_error", app=entry.name, exc_info=True)
            continue

        plugin = getattr(module, "PLUGIN", None)
        if plugin is None or not isinstance(plugin, AppPluginBase):
            logger.warning(
                "plugin_discovery_no_PLUGIN",
                app=entry.name,
                detail="plugin.py must define PLUGIN = YourPlugin()",
            )
            continue

        # Check feature flag
        flag_name = plugin.feature_flag
        flag_value = os.environ.get(flag_name, "true")  # default enabled
        if flag_value.lower() not in ("1", "true", "yes"):
            logger.info("plugin_disabled_by_flag", name=plugin.name, flag=flag_name)
            continue

        registry.register(plugin)

    logger.info("plugin_discovery_complete", count=len(registry))
    return registry
