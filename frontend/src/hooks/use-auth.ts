import { useCallback, useSyncExternalStore } from "react"

const AUTH_KEY = "api-key"

function getSnapshot(): string | null {
  try {
    return localStorage.getItem(AUTH_KEY)
  } catch {
    return null
  }
}

function subscribe(callback: () => void): () => void {
  const handler = (e: StorageEvent) => {
    if (e.key === AUTH_KEY) callback()
  }
  window.addEventListener("storage", handler)
  // Also listen for custom events (same-tab updates)
  window.addEventListener("auth-change", callback)
  return () => {
    window.removeEventListener("storage", handler)
    window.removeEventListener("auth-change", callback)
  }
}

export function useAuth() {
  const apiKey = useSyncExternalStore(subscribe, getSnapshot, () => null)

  const setApiKey = useCallback((key: string) => {
    try {
      localStorage.setItem(AUTH_KEY, key)
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("auth-change"))
  }, [])

  const clearApiKey = useCallback(() => {
    try {
      localStorage.removeItem(AUTH_KEY)
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("auth-change"))
  }, [])

  return {
    apiKey,
    isAuthenticated: !!apiKey,
    setApiKey,
    clearApiKey,
  }
}
