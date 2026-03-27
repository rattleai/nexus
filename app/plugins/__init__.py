"""Plugin framework for application layer separation.

Infrastructure code uses this package to discover and register
application plugins that live under ``app.apps.*``.
"""

from app.plugins.base import AppPluginBase, FrontendManifest, NavItem
from app.plugins.registry import discover_plugins, registry

__all__ = [
    "AppPluginBase",
    "FrontendManifest",
    "NavItem",
    "discover_plugins",
    "registry",
]
