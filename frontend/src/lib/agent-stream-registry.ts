/**
 * Agent Stream Registry — bridges run-stream SSE connections across route transitions.
 *
 * When a user starts an agent run (via Ctrl+K or New Run dialog), the POST to
 * /run-stream returns an SSE stream. This registry holds the connection so
 * the sessions page can pick it up after navigation.
 *
 * Uses useSyncExternalStore pattern for React integration.
 */

import { getAccessToken } from "@/lib/api-client"
import { queryClient } from "@/lib/query-client"
import { agentKeys } from "@/hooks/use-agents"
import type { ToolCallEntry } from "@/components/agents/sessions/tool-call-card"

// ── Types (matching stream-view.tsx) ────────────────────

export interface ContentEntry {
  id: string
  type: "content"
  text: string
  timestamp: number
}

export interface StepEntry {
  id: string
  type: "step"
  step: number
  tokens?: number
  cost?: number
  timestamp: number
}

export interface ThinkingEntry {
  id: string
  type: "thinking"
  content: string
  tokens?: number
  cost?: number
  timestamp: number
}

export interface StatusEntry {
  id: string
  type: "status"
  status: string
  message?: string
  timestamp: number
}

export type StreamEntry = ContentEntry | ToolCallEntry | StepEntry | StatusEntry | ThinkingEntry

type RunStatus = "streaming" | "completed" | "error"

interface ActiveStream {
  instanceId: string
  definitionId: string
  sessionId?: string
  entries: StreamEntry[]
  listeners: Set<() => void>
  abort: AbortController
  status: RunStatus
}

// ── Registry singleton ──────────────────────────────────

const registry = new Map<string, ActiveStream>()

const CLEANUP_DELAY_MS = 5 * 60 * 1000 // 5 minutes

function notifyListeners(stream: ActiveStream) {
  for (const listener of stream.listeners) {
    listener()
  }
}

// ── SSE Parser ──────────────────────────────────────────

async function consumeStream(stream: ActiveStream, reader: ReadableStream<Uint8Array>) {
  const decoder = new TextDecoder()
  const bodyReader = reader.getReader()
  let lineBuffer = ""
  let currentEventType = ""
  const toolCallMap = new Map<string, string>() // toolName → entryId

  try {
    while (true) {
      if (stream.abort.signal.aborted) break
      const { done, value } = await bodyReader.read()
      if (done) break

      lineBuffer += decoder.decode(value, { stream: true })
      if (lineBuffer.length > 1_000_000) {
        lineBuffer = lineBuffer.slice(-100_000)
      }

      const lines = lineBuffer.split("\n")
      lineBuffer = lines.pop() ?? ""

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEventType = line.slice(7).trim()
          continue
        }
        if (!line.startsWith("data: ")) continue
        const raw = line.slice(6).trim()
        if (raw === "[DONE]") continue

        try {
          const parsed = JSON.parse(raw)
          const now = Date.now()

          switch (currentEventType) {
            case "run_started":
            case "session_started":
            case "turn_started":
              // Session/turn metadata — store sessionId if present
              if (parsed.session_id && !stream.sessionId) {
                stream.sessionId = parsed.session_id
              }
              break

            case "thinking": {
              stream.entries.push({
                id: crypto.randomUUID(),
                type: "thinking",
                content: parsed.content ?? "",
                tokens: parsed.tokens,
                cost: parsed.cost_usd,
                timestamp: now,
              })
              notifyListeners(stream)
              break
            }

            case "content_delta": {
              if (parsed.content) {
                const last = stream.entries[stream.entries.length - 1]
                if (last && last.type === "content") {
                  last.text += parsed.content
                } else {
                  stream.entries.push({
                    id: crypto.randomUUID(),
                    type: "content",
                    text: parsed.content,
                    timestamp: now,
                  })
                }
                notifyListeners(stream)
              }
              break
            }

            case "tool_call": {
              if (parsed.tool_name) {
                const entryId = crypto.randomUUID()
                toolCallMap.set(parsed.tool_name, entryId)
                stream.entries.push({
                  id: entryId,
                  type: "tool_call",
                  toolName: parsed.tool_name,
                  args: parsed.arguments ?? {},
                  status: "running",
                  timestamp: now,
                })
                notifyListeners(stream)
              }
              break
            }

            case "tool_result": {
              if (parsed.tool_name) {
                const entryId = toolCallMap.get(parsed.tool_name)
                if (entryId) {
                  const entry = stream.entries.find((e) => e.id === entryId)
                  if (entry && entry.type === "tool_call") {
                    entry.status = "completed"
                    entry.result = parsed.result
                    entry.durationMs = now - entry.timestamp
                  }
                  notifyListeners(stream)
                }
              }
              break
            }

            case "step_completed":
            case "step_started": {
              if (currentEventType === "step_completed") {
                stream.entries.push({
                  id: crypto.randomUUID(),
                  type: "step",
                  step: parsed.step_number ?? parsed.step ?? 0,
                  tokens: parsed.tokens,
                  cost: parsed.cost_usd ?? parsed.cost,
                  timestamp: now,
                })
                notifyListeners(stream)
              }
              break
            }

            case "run_completed": {
              stream.entries.push({
                id: crypto.randomUUID(),
                type: "status",
                status: "completed",
                message: parsed.finish_reason,
                timestamp: now,
              })
              stream.status = "completed"
              notifyListeners(stream)
              break
            }

            case "error": {
              stream.entries.push({
                id: crypto.randomUUID(),
                type: "status",
                status: "failed",
                message: parsed.message,
                timestamp: now,
              })
              stream.status = "error"
              notifyListeners(stream)
              break
            }
          }
        } catch {
          // skip malformed SSE data
        }
      }
    }

    // Stream ended — mark completed if not already
    if (stream.status === "streaming") {
      stream.status = "completed"
      notifyListeners(stream)
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return
    stream.status = "error"
    notifyListeners(stream)
  } finally {
    // Invalidate instance query caches so sidebar picks up the new/updated instance
    queryClient.invalidateQueries({ queryKey: agentKeys.instances.all })

    // Auto-cleanup after delay
    setTimeout(() => {
      registry.delete(stream.instanceId)
    }, CLEANUP_DELAY_MS)
  }
}

// ── Public API ──────────────────────────────────────────

/**
 * Start an agent run via the run-stream endpoint.
 * Returns the instanceId once the stream begins.
 * The SSE connection is held in the registry for the session page to consume.
 */
export async function startRun(agentId: string, prompt: string): Promise<string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const token = getAccessToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const controller = new AbortController()

  const response = await fetch(`/api/v1/agents/definitions/${agentId}/run-stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      input_data: { prompt },
    }),
    signal: controller.signal,
  })

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errBody = await response.json()
      if (errBody.detail) errorMessage = errBody.detail
    } catch {
      // use default
    }
    throw new Error(errorMessage)
  }

  // Read instance_id from header (primary) or first SSE event (fallback)
  let instanceId = response.headers.get("X-Instance-Id")

  if (!instanceId && response.body) {
    // Fallback: peek at the first SSE event to get instance_id
    // We'll read from the stream and parse the run_started event
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    // Read until we get the run_started event
    while (!instanceId) {
      const { done, value } = await reader.read()
      if (done) throw new Error("Stream ended before run_started event")

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const parsed = JSON.parse(line.slice(6))
            if (parsed.instance_id) {
              instanceId = parsed.instance_id
              break
            }
          } catch {
            // continue
          }
        }
      }
    }

    // We've consumed some data. We need to create a new ReadableStream
    // that starts with the remaining buffer + continues from the reader.
    const remainingBuffer = new TextEncoder().encode(buffer)
    const combinedStream = new ReadableStream<Uint8Array>({
      async start(ctrl) {
        // First push remaining buffered data
        ctrl.enqueue(remainingBuffer)
        // Then continue from original reader
        try {
          while (true) {
            const { done: d, value: v } = await reader.read()
            if (d) { ctrl.close(); break }
            ctrl.enqueue(v)
          }
        } catch (e) {
          ctrl.error(e)
        }
      },
    })

    // Register and consume
    const stream: ActiveStream = {
      instanceId,
      definitionId: agentId,
      entries: [],
      listeners: new Set(),
      abort: controller,
      status: "streaming",
    }
    registry.set(instanceId, stream)
    consumeStream(stream, combinedStream)

    return instanceId
  }

  if (!instanceId) {
    throw new Error("No instance ID returned from run-stream")
  }

  // Register and consume (header path — body not yet consumed)
  const stream: ActiveStream = {
    instanceId,
    definitionId: agentId,
    entries: [],
    listeners: new Set(),
    abort: controller,
    status: "streaming",
  }
  registry.set(instanceId, stream)

  if (response.body) {
    consumeStream(stream, response.body)
  }

  return instanceId
}

/**
 * Get the current entries snapshot for an instance.
 * Returns null if no active stream exists.
 */
export function getEntries(instanceId: string): StreamEntry[] | null {
  return registry.get(instanceId)?.entries ?? null
}

/**
 * Get the current status of a stream.
 */
export function getStatus(instanceId: string): RunStatus | null {
  return registry.get(instanceId)?.status ?? null
}

/**
 * Subscribe to entry changes for a specific instance.
 * Returns an unsubscribe function.
 */
export function subscribe(instanceId: string, callback: () => void): () => void {
  const stream = registry.get(instanceId)
  if (!stream) return () => {}
  stream.listeners.add(callback)
  return () => {
    stream.listeners.delete(callback)
  }
}

/**
 * Check if a stream exists for this instance.
 */
export function hasStream(instanceId: string): boolean {
  return registry.has(instanceId)
}

/**
 * Get the sessionId associated with a stream (set by session_started/turn_started events).
 */
export function getSessionId(instanceId: string): string | null {
  return registry.get(instanceId)?.sessionId ?? null
}

/**
 * Start a new interactive conversation via the conversations endpoint.
 * Returns { sessionId, instanceId } once the stream begins.
 */
export async function startConversation(
  agentId: string,
  prompt: string,
): Promise<{ sessionId: string; instanceId: string }> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const token = getAccessToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const controller = new AbortController()

  const response = await fetch(`/api/v1/agents/definitions/${agentId}/conversations`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      input_data: { prompt },
    }),
    signal: controller.signal,
  })

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errBody = await response.json()
      if (errBody.detail) errorMessage = errBody.detail
    } catch {
      // use default
    }
    throw new Error(errorMessage)
  }

  const instanceId = response.headers.get("X-Instance-Id")
  const sessionId = response.headers.get("X-Session-Id")

  if (!instanceId || !sessionId) {
    throw new Error("Missing instance or session ID from conversations endpoint")
  }

  const stream: ActiveStream = {
    instanceId,
    definitionId: agentId,
    sessionId,
    entries: [],
    listeners: new Set(),
    abort: controller,
    status: "streaming",
  }
  registry.set(instanceId, stream)

  if (response.body) {
    consumeStream(stream, response.body)
  }

  return { sessionId, instanceId }
}

/**
 * Send a follow-up message in an existing conversation.
 * Returns the new instanceId for this turn.
 */
export async function sendReply(
  sessionId: string,
  message: string,
): Promise<string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const token = getAccessToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const controller = new AbortController()

  const response = await fetch(`/api/v1/agents/sessions/${sessionId}/reply`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
    signal: controller.signal,
  })

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errBody = await response.json()
      if (errBody.detail) errorMessage = errBody.detail
    } catch {
      // use default
    }
    throw new Error(errorMessage)
  }

  const instanceId = response.headers.get("X-Instance-Id")
  if (!instanceId) {
    throw new Error("No instance ID returned from reply endpoint")
  }

  const stream: ActiveStream = {
    instanceId,
    definitionId: "",
    sessionId,
    entries: [],
    listeners: new Set(),
    abort: controller,
    status: "streaming",
  }
  registry.set(instanceId, stream)

  if (response.body) {
    consumeStream(stream, response.body)
  }

  return instanceId
}

/**
 * React hook to consume stream entries using useSyncExternalStore.
 */
export function useRegistryStream(instanceId: string) {
  const subscribeToStore = React.useCallback(
    (callback: () => void) => subscribe(instanceId, callback),
    [instanceId],
  )

  const getSnapshot = React.useCallback(
    () => getEntries(instanceId),
    [instanceId],
  )

  const getStatusSnapshot = React.useCallback(
    () => getStatus(instanceId),
    [instanceId],
  )

  const entries = React.useSyncExternalStore(subscribeToStore, getSnapshot, getSnapshot)
  const status = React.useSyncExternalStore(subscribeToStore, getStatusSnapshot, getStatusSnapshot)

  return {
    entries,
    status,
    isActive: status === "streaming",
    hasStream: entries !== null,
  }
}

// Need React import for useSyncExternalStore
import * as React from "react"
