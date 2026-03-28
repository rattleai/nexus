/**
 * Frontend plugin manifest registry.
 *
 * Fetches the enabled plugin manifests from the backend and provides
 * nav items for the sidebar. Infrastructure nav items are defined
 * statically; plugin nav items are merged in dynamically.
 */

import { useQuery } from "@tanstack/react-query"

export interface PluginNavItem {
  href: string
  labelKey: string
  icon: string
  order: number
  plugin: string
}

export interface PluginInfo {
  name: string
  displayName: string
  version: string
}

export interface PluginManifest {
  plugins: PluginInfo[]
  nav_items: PluginNavItem[]
}

/**
 * Fetch the plugin manifest from the backend.
 * Returns nav items and plugin metadata for all enabled plugins.
 */
export function usePluginManifest() {
  return useQuery<PluginManifest>({
    queryKey: ["plugins", "manifest"],
    queryFn: async () => {
      const res = await fetch("/api/v1/plugins/manifest")
      if (!res.ok) {
        // Fallback: return empty manifest if endpoint unavailable
        return { plugins: [], nav_items: [] }
      }
      return res.json()
    },
    staleTime: Infinity, // Stable for the session — plugins don't change at runtime
    retry: false,
  })
}
