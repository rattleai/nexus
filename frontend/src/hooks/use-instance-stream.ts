import * as React from "react"
import { getAccessToken } from "@/lib/api-client"
import type { AgentStreamEvent } from "@/types/agents"

interface UseInstanceStreamOptions {
  instanceId: string | null
  onEvent?: (event: AgentStreamEvent) => void
  onDone?: () => void
  onError?: (error: Error) => void
  enabled?: boolean
}

/**
 * SSE hook for observing an already-running agent instance.
 *
 * Connects to GET /instances/{id}/stream (Redis Streams-backed SSE)
 * to receive real-time step events from the agent runtime.
 */
export function useInstanceStream({
  instanceId,
  onEvent,
  onDone,
  onError,
  enabled = true,
}: UseInstanceStreamOptions) {
  const [isConnected, setIsConnected] = React.useState(false)
  const [error, setError] = React.useState<Error | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  const onEventRef = React.useRef(onEvent)
  const onDoneRef = React.useRef(onDone)
  const onErrorRef = React.useRef(onError)
  onEventRef.current = onEvent
  onDoneRef.current = onDone
  onErrorRef.current = onError

  const disconnect = React.useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsConnected(false)
  }, [])

  React.useEffect(() => {
    if (!instanceId || !enabled) {
      disconnect()
      return
    }

    const controller = new AbortController()
    abortRef.current = controller

    const connect = async () => {
      try {
        const headers: Record<string, string> = {}
        const token = getAccessToken()
        if (token) headers["Authorization"] = `Bearer ${token}`

        const response = await fetch(
          `/api/v1/agents/instances/${instanceId}/stream`,
          { headers, signal: controller.signal },
        )

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const reader = response.body?.getReader()
        if (!reader) throw new Error("Response body is not readable")

        setIsConnected(true)
        setError(null)

        const decoder = new TextDecoder()
        let lineBuffer = ""
        let currentEventType = ""

        while (true) {
          if (controller.signal.aborted) break
          const { done, value } = await reader.read()
          if (done) break

          lineBuffer += decoder.decode(value, { stream: true })
          if (lineBuffer.length > 500_000) {
            lineBuffer = lineBuffer.slice(-50_000)
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
              const data = JSON.parse(raw)
              onEventRef.current?.({
                event: currentEventType || "message",
                data,
              })

              if (
                currentEventType === "run_completed" ||
                currentEventType === "instance_completed" ||
                currentEventType === "instance_failed"
              ) {
                onDoneRef.current?.()
              }
            } catch {
              // skip malformed SSE data
            }
          }
        }

        setIsConnected(false)
        onDoneRef.current?.()
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return
        const streamError = err instanceof Error ? err : new Error("Stream failed")
        setError(streamError)
        setIsConnected(false)
        onErrorRef.current?.(streamError)
      }
    }

    connect()
    return () => {
      controller.abort()
      abortRef.current = null
    }
  }, [instanceId, enabled, disconnect])

  return { isConnected, error, disconnect }
}
