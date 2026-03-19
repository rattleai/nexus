import * as React from "react"
import { getAccessToken } from "@/lib/api-client"

export interface AgentStreamMessage {
  id: string
  role: "user" | "assistant"
  content: string
  toolCalls?: Array<{
    id: string
    name: string
    arguments: Record<string, unknown>
    status: "pending" | "running" | "completed" | "error"
    result?: unknown
    error?: string
    duration?: number
  }>
  thinking?: string
  tokens?: number
  cost?: number
  steps?: number
}

interface UseAgentStreamOptions {
  agentId: string
  onError?: (error: Error) => void
  onFinish?: (message: AgentStreamMessage) => void
}

export function useAgentStream({
  agentId,
  onError,
  onFinish,
}: UseAgentStreamOptions) {
  const [messages, setMessages] = React.useState<AgentStreamMessage[]>([])
  const [isStreaming, setIsStreaming] = React.useState(false)
  const [agentState, setAgentState] = React.useState<
    "idle" | "thinking" | "acting" | "complete" | "error"
  >("idle")
  const [error, setError] = React.useState<Error | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  const messagesRef = React.useRef(messages)
  messagesRef.current = messages

  React.useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // Reset state when agentId changes
  React.useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setMessages([])
    setIsStreaming(false)
    setAgentState("idle")
    setError(null)
  }, [agentId])

  const stop = React.useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsStreaming(false)
    setAgentState("idle")
  }, [])

  const sendMessage = React.useCallback(
    async (content: string) => {
      if (isStreaming) return
      setError(null)
      setAgentState("thinking")

      const userMsg: AgentStreamMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
      }

      const assistantMsg: AgentStreamMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        toolCalls: [],
      }

      // Snapshot history before adding new messages
      const currentMessages = messagesRef.current
      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setIsStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        }
        const token = getAccessToken()
        if (token) {
          headers["Authorization"] = `Bearer ${token}`
        }

        const response = await fetch(`/api/v1/agents/definitions/${agentId}/run-stream`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            input_data: {
              messages: [
                ...currentMessages.map((m) => ({
                  role: m.role,
                  content: m.content,
                })),
                { role: "user", content },
              ],
            },
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          // Parse the backend error message instead of raw HTTP status
          let errorMessage = `HTTP ${response.status}: ${response.statusText}`
          try {
            const errBody = await response.json()
            if (errBody.detail) errorMessage = errBody.detail
          } catch {
            // use default message
          }
          throw new Error(errorMessage)
        }

        const reader = response.body?.getReader()
        if (!reader) throw new Error("Response body is not readable")

        const decoder = new TextDecoder()
        let accumulated = ""
        let lineBuffer = ""
        let totalTokens = 0
        let totalCost = 0
        let totalSteps = 0
        // Track tool calls by name for matching tool_call -> tool_result
        const toolCalls: NonNullable<AgentStreamMessage["toolCalls"]> = []
        let currentEventType = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          lineBuffer += decoder.decode(value, { stream: true })
          // Prevent unbounded buffer growth on hung connections
          if (lineBuffer.length > 1_000_000) {
            lineBuffer = lineBuffer.slice(-100_000)
          }
          const lines = lineBuffer.split("\n")
          lineBuffer = lines.pop() ?? ""

          for (const line of lines) {
            // Track current event type from SSE "event:" lines
            if (line.startsWith("event: ")) {
              currentEventType = line.slice(7).trim()
              if (currentEventType === "thinking") setAgentState("thinking")
              else if (currentEventType === "tool_call") setAgentState("acting")
              else if (currentEventType === "content_delta") setAgentState("thinking")
              continue
            }

            if (!line.startsWith("data: ")) continue
            const raw = line.slice(6).trim()
            if (raw === "[DONE]") continue

            try {
              const parsed = JSON.parse(raw)

              // Handle based on the SSE event type from the preceding "event:" line
              switch (currentEventType) {
                case "content_delta":
                  if (parsed.content) {
                    accumulated += parsed.content
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsg.id
                          ? { ...m, content: accumulated }
                          : m,
                      ),
                    )
                  }
                  break

                case "thinking":
                  // Backend emits: {tokens, cost_usd}
                  if (parsed.tokens) totalTokens += parsed.tokens
                  if (parsed.cost_usd) totalCost += parsed.cost_usd
                  break

                case "step_started":
                  if (parsed.step_number) totalSteps = parsed.step_number
                  break

                case "tool_call":
                  // Backend emits: {tool_name, arguments}
                  if (parsed.tool_name) {
                    toolCalls.push({
                      id: crypto.randomUUID(),
                      name: parsed.tool_name,
                      arguments: parsed.arguments ?? {},
                      status: "running",
                    })
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsg.id
                          ? { ...m, toolCalls: [...toolCalls] }
                          : m,
                      ),
                    )
                  }
                  break

                case "tool_result":
                  // Backend emits: {tool_name, result}
                  // Match by tool_name to update the correct tool call
                  if (parsed.tool_name && toolCalls.length > 0) {
                    const matchIdx = toolCalls.findLastIndex(
                      (tc) => tc.name === parsed.tool_name && tc.status === "running",
                    )
                    const idx = matchIdx >= 0 ? matchIdx : toolCalls.length - 1
                    toolCalls[idx].status = "completed"
                    toolCalls[idx].result = parsed.result
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsg.id
                          ? { ...m, toolCalls: [...toolCalls] }
                          : m,
                      ),
                    )
                  }
                  break

                case "run_completed":
                  // Backend emits: {finish_reason, output, total_tokens?, total_cost_usd?}
                  if (parsed.total_tokens) totalTokens = parsed.total_tokens
                  if (parsed.total_cost_usd) totalCost = parsed.total_cost_usd
                  break

                case "error":
                  // Backend emits: {message}
                  if (parsed.message) {
                    setError(new Error(parsed.message))
                  }
                  break
              }
            } catch {
              // skip malformed SSE data
            }
          }
        }

        // Finalize: mark any still-running tool calls as completed
        for (const tc of toolCalls) {
          if (tc.status === "running") {
            tc.status = "completed"
          }
        }

        const finalMsg: AgentStreamMessage = {
          ...assistantMsg,
          content: accumulated,
          toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
          tokens: totalTokens,
          cost: totalCost,
          steps: totalSteps,
        }

        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMsg.id ? finalMsg : m)),
        )
        setAgentState("complete")
        onFinish?.(finalMsg)
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return
        const streamError = err instanceof Error ? err : new Error("Stream failed")
        setError(streamError)
        setAgentState("error")
        onError?.(streamError)
        // Preserve partial content on error instead of deleting the message
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: m.content || "An error occurred." }
              : m,
          ),
        )
      } finally {
        setIsStreaming(false)
        abortRef.current = null
      }
    },
    [agentId, isStreaming, onError, onFinish],
  )

  const clearMessages = React.useCallback(() => {
    setMessages([])
    setAgentState("idle")
    setError(null)
  }, [])

  return {
    messages,
    sendMessage,
    isStreaming,
    agentState,
    error,
    stop,
    clearMessages,
    setMessages,
  }
}
