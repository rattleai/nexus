/**
 * Configures the @hey-api generated API client with auth and base URL.
 *
 * Import this module once at app startup (e.g. in main.tsx) to wire up
 * the generated SDK with the same auth tokens used by the hand-written
 * api-client.ts.
 *
 * Usage:
 *   import { initGeneratedClient } from "@/lib/generated-client"
 *   initGeneratedClient()
 *
 * Then use the generated SDK anywhere:
 *   import { getHealthLive } from "@/generated/api"
 *   const response = await getHealthLive()
 */

import { getAccessToken } from "./api-client"
import { AUTH_STORAGE_KEY } from "./constants"

let _initialized = false

/**
 * Initialize the @hey-api generated client with auth interceptors.
 * Safe to call multiple times — only runs once.
 */
export function initGeneratedClient(): void {
  if (_initialized) return

  // Lazy import so the app still builds before the first codegen run.
  // The generated module exposes a `client` singleton with a config method.
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { client } = require("@/generated/api") as {
      client: {
        setConfig: (cfg: Record<string, unknown>) => void
        interceptors: {
          request: { use: (fn: (req: Request) => Request) => void }
        }
      }
    }

    client.setConfig({
      baseUrl: "/api/v1",
    })

    client.interceptors.request.use((request: Request) => {
      const token = getAccessToken()
      if (token) {
        request.headers.set("Authorization", `Bearer ${token}`)
      } else {
        try {
          const apiKey = localStorage.getItem(AUTH_STORAGE_KEY)
          if (apiKey) {
            request.headers.set("X-API-Key", apiKey)
          }
        } catch {
          // localStorage may be unavailable
        }
      }
      return request
    })

    _initialized = true
  } catch {
    // Generated client not yet available — codegen hasn't been run.
    // This is expected during initial setup; the hand-written api-client
    // continues to work as a fallback.
    console.debug("[generated-client] SDK not yet generated — run `npm run api:generate`")
  }
}
