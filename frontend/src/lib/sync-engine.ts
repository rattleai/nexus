import { api } from "./api-client"

interface ChangeRecord {
  id: string
  entity_type: string
  entity_id: string
  operation: "create" | "update" | "delete"
  changed_fields: Record<string, unknown> | null
  sync_version: number
  created_at: string
}

interface SyncChangesResponse {
  changes: ChangeRecord[]
  latest_version: number
  has_more: boolean
}

interface SyncPushRequest {
  entity_type: string
  entity_id: string
  operation: "create" | "update"
  data: Record<string, unknown>
  client_version: number
}

interface SyncPushResponse {
  accepted: Array<{ entity_id: string; server_version: number }>
  conflicts: Array<{ entity_id: string; server_version: number; server_data: Record<string, unknown> }>
}

const SYNC_VERSION_KEY = "cadprice-sync-version"
const PENDING_CHANGES_KEY = "cadprice-pending-changes"

/**
 * Offline-first sync engine.
 * Stores data in localStorage (simple) with sync version tracking.
 * Queues mutations when offline and replays on reconnect.
 */
class SyncEngine {
  private _syncVersion: number
  private _pendingChanges: SyncPushRequest[]
  private _listeners = new Set<() => void>()
  private _syncing = false

  constructor() {
    this._syncVersion = this.loadSyncVersion()
    this._pendingChanges = this.loadPendingChanges()
    window.addEventListener("online", () => this.sync())
  }

  get syncVersion(): number {
    return this._syncVersion
  }

  get pendingCount(): number {
    return this._pendingChanges.length
  }

  get isSyncing(): boolean {
    return this._syncing
  }

  subscribe(callback: () => void): () => void {
    this._listeners.add(callback)
    return () => this._listeners.delete(callback)
  }

  private notify() {
    this._listeners.forEach((cb) => cb())
  }

  /**
   * Queue a mutation for sync. If online, syncs immediately.
   */
  queueChange(change: SyncPushRequest): void {
    this._pendingChanges.push(change)
    this.savePendingChanges()
    this.notify()

    if (navigator.onLine) {
      this.sync()
    }
  }

  /**
   * Pull remote changes since last sync version, then push pending local changes.
   */
  async sync(): Promise<SyncChangesResponse | null> {
    if (this._syncing || !navigator.onLine) return null
    this._syncing = true
    this.notify()

    try {
      // Pull changes
      const response = await api
        .get("sync/changes", {
          searchParams: {
            since_version: this._syncVersion,
            limit: 100,
          },
        })
        .json<SyncChangesResponse>()

      if (response.latest_version > this._syncVersion) {
        this._syncVersion = response.latest_version
        this.saveSyncVersion()
      }

      // Push pending changes
      if (this._pendingChanges.length > 0) {
        const pushResponse = await api
          .post("sync/push", { json: { changes: this._pendingChanges } })
          .json<SyncPushResponse>()

        // Remove accepted changes from pending queue
        const acceptedIds = new Set(pushResponse.accepted.map((a) => a.entity_id))
        this._pendingChanges = this._pendingChanges.filter(
          (c) => !acceptedIds.has(c.entity_id),
        )
        this.savePendingChanges()
      }

      this.notify()
      return response
    } catch {
      // Sync failed — will retry on next online event or manual trigger
      return null
    } finally {
      this._syncing = false
      this.notify()
    }
  }

  private loadSyncVersion(): number {
    try {
      return parseInt(localStorage.getItem(SYNC_VERSION_KEY) ?? "0", 10) || 0
    } catch {
      return 0
    }
  }

  private saveSyncVersion(): void {
    try {
      localStorage.setItem(SYNC_VERSION_KEY, String(this._syncVersion))
    } catch {
      // ignore
    }
  }

  private loadPendingChanges(): SyncPushRequest[] {
    try {
      return JSON.parse(localStorage.getItem(PENDING_CHANGES_KEY) ?? "[]")
    } catch {
      return []
    }
  }

  private savePendingChanges(): void {
    try {
      localStorage.setItem(PENDING_CHANGES_KEY, JSON.stringify(this._pendingChanges))
    } catch {
      // ignore
    }
  }
}

export const syncEngine = new SyncEngine()
