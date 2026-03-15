import { getAccessToken } from "./api-client"

type EventType = "notification" | "job_update" | "presence" | "sync" | "ping"

interface WSEvent {
  type: EventType
  data: Record<string, unknown>
}

type EventHandler = (event: WSEvent) => void

/**
 * Auto-reconnecting WebSocket client with exponential backoff.
 * Integrates with JWT auth and provides an event-based API.
 */
class WebSocketClient {
  private ws: WebSocket | null = null
  private url: string
  private handlers = new Map<EventType | "*", Set<EventHandler>>()
  private reconnectAttempts = 0
  private maxReconnectDelay = 30_000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private _isConnected = false
  private _listeners = new Set<() => void>()

  constructor(baseUrl?: string) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const host = baseUrl ?? `${protocol}//${window.location.host}`
    this.url = `${host}/api/v1/ws`

    // Reconnect with a fresh token whenever auth state changes.
    // This ensures the WS connection uses the latest JWT after a refresh,
    // and disconnects cleanly when the user logs out.
    window.addEventListener("auth-change", () => {
      const token = getAccessToken()
      if (token && this.ws?.readyState !== WebSocket.OPEN) {
        // Auth restored or token refreshed — reconnect with the new token
        this.disconnect()
        this.reconnectAttempts = 0
        this.connect()
      } else if (token && this.ws?.readyState === WebSocket.OPEN) {
        // Token refreshed while connected — reconnect to use new token
        this.disconnect()
        this.reconnectAttempts = 0
        this.connect()
      } else if (!token && this.ws) {
        // Auth lost — disconnect
        this.disconnect()
      }
    })
  }

  get isConnected(): boolean {
    return this._isConnected
  }

  subscribe(callback: () => void): () => void {
    this._listeners.add(callback)
    return () => this._listeners.delete(callback)
  }

  private notify() {
    this._listeners.forEach((cb) => cb())
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return

    const token = getAccessToken()
    const wsUrl = token ? `${this.url}?token=${encodeURIComponent(token)}` : this.url

    try {
      this.ws = new WebSocket(wsUrl)
    } catch {
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this._isConnected = true
      this.notify()
      this.startHeartbeat()
    }

    this.ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as WSEvent
        if (parsed.type === "ping") return // heartbeat response
        this.emit(parsed)
      } catch {
        // ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this._isConnected = false
      this.notify()
      this.stopHeartbeat()
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.stopHeartbeat()
    this.ws?.close()
    this.ws = null
    this._isConnected = false
    this.notify()
  }

  on(type: EventType | "*", handler: EventHandler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set())
    this.handlers.get(type)!.add(handler)
    return () => this.handlers.get(type)?.delete(handler)
  }

  private emit(event: WSEvent) {
    this.handlers.get(event.type)?.forEach((h) => h(event))
    this.handlers.get("*")?.forEach((h) => h(event))
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private startHeartbeat() {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping" }))
      }
    }, 30_000)
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }
}

export const wsClient = new WebSocketClient()
