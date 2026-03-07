import { useCallback, useEffect, useSyncExternalStore } from "react"
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

  const getSnapshot = useCallback(
    (): SyncState => ({
      syncVersion: syncEngine.syncVersion,
      pendingCount: syncEngine.pendingCount,
      isSyncing: syncEngine.isSyncing,
      isOnline: typeof navigator !== "undefined" ? navigator.onLine : true,
    }),
    [],
  )

  const state = useSyncExternalStore(subscribe, getSnapshot)

  // Track online/offline status changes
  useEffect(() => {
    const handleOnline = () => {
      // Force a re-render by triggering sync
      syncEngine.sync()
    }
    window.addEventListener("online", handleOnline)
    return () => window.removeEventListener("online", handleOnline)
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
