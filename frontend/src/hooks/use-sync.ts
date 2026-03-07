import { useCallback, useEffect, useRef, useSyncExternalStore } from "react"
import { syncEngine } from "@/lib/sync-engine"

interface SyncState {
  syncVersion: number
  pendingCount: number
  isSyncing: boolean
  isOnline: boolean
}

/**
 * React hook for the offline-first sync engine.
 *
 * Exposes sync state (version, pending changes, syncing status)
 * and a manual sync trigger for pull-to-refresh or retry flows.
 *
 * @example
 * ```tsx
 * function SyncStatus() {
 *   const { pendingCount, isSyncing, sync } = useSync()
 *   return (
 *     <div>
 *       {isSyncing && <Spinner />}
 *       {pendingCount > 0 && <span>{pendingCount} pending</span>}
 *       <button onClick={sync}>Sync now</button>
 *     </div>
 *   )
 * }
 * ```
 */
export function useSync(): SyncState & {
  sync: () => Promise<void>
  queueChange: typeof syncEngine.queueChange
} {
  const subscribe = useCallback(
    (callback: () => void) => syncEngine.subscribe(callback),
    [],
  )

  // Cache the snapshot to preserve referential identity when values don't change
  const cachedSnapshot = useRef<SyncState>({
    syncVersion: 0,
    pendingCount: 0,
    isSyncing: false,
    isOnline: true,
  })

  const getSnapshot = useCallback((): SyncState => {
    const next: SyncState = {
      syncVersion: syncEngine.syncVersion,
      pendingCount: syncEngine.pendingCount,
      isSyncing: syncEngine.isSyncing,
      isOnline: typeof navigator !== "undefined" ? navigator.onLine : true,
    }
    const prev = cachedSnapshot.current
    if (
      prev.syncVersion === next.syncVersion &&
      prev.pendingCount === next.pendingCount &&
      prev.isSyncing === next.isSyncing &&
      prev.isOnline === next.isOnline
    ) {
      return prev
    }
    cachedSnapshot.current = next
    return next
  }, [])

  const state = useSyncExternalStore(subscribe, getSnapshot)

  // Track online/offline status changes
  useEffect(() => {
    const handleOnline = () => {
      syncEngine.sync()
    }
    const handleOffline = () => {
      // Trigger re-render to update isOnline
      cachedSnapshot.current = { ...cachedSnapshot.current, isOnline: false }
    }
    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)
    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
    }
  }, [])

  const sync = useCallback(async () => {
    await syncEngine.sync()
  }, [])

  const queueChange = useCallback(
    (...args: Parameters<typeof syncEngine.queueChange>) =>
      syncEngine.queueChange(...args),
    [],
  )

  return {
    ...state,
    sync,
    queueChange,
  }
}
