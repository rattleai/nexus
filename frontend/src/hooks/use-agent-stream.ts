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

  const stop = React.useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsStreaming(false)
    setAgentState("idle")
  }, [])

  const sendMessage = React.useCallback(
    async (content: string) => {
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
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const reader = response.body?.getReader()
        if (!reader) throw new Error("Response body is not readable")

        const decoder = new TextDecoder()
        let accumulated = ""
        let lineBuffer = ""
        let totalTokens = 0
        let totalCost = 0
        let totalSteps = 0
        const toolCalls: AgentStreamMessage["toolCalls"] = []

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          lineBuffer += decoder.decode(value, { stream: true })
          const lines = lineBuffer.split("\n")
          lineBuffer = lines.pop() ?? ""

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              const eventType = line.slice(7).trim()
              if (eventType === "thinking") setAgentState("thinking")
              else if (eventType === "tool_call") setAgentState("acting")
              else if (eventType === "content_delta") setAgentState("thinking")
              continue
            }

            if (!line.startsWith("data: ")) continue
            const raw = line.slice(6).trim()
            if (raw === "[DONE]") continue

            try {
              const parsed = JSON.parse(raw)

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

              if (parsed.tool_name) {
                const tc = {
                  id: crypto.randomUUID(),
                  name: parsed.tool_name,
                  arguments: parsed.tool_args ?? parsed.arguments ?? {},
                  status: "running" as const,
                  result: parsed.tool_result,
                  duration: parsed.duration,
                }
                toolCalls!.push(tc)
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, toolCalls: [...toolCalls!] }
                      : m,
                  ),
                )
              }

              if (parsed.tool_result !== undefined && toolCalls!.length > 0) {
                const last = toolCalls![toolCalls!.length - 1]
                last.status = parsed.error ? "error" : "completed"
                last.result = parsed.tool_result
                last.error = parsed.error
                last.duration = parsed.duration
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, toolCalls: [...toolCalls!] }
                      : m,
                  ),
                )
              }

              if (parsed.tokens) totalTokens += parsed.tokens
              if (parsed.cost) totalCost += parsed.cost
              if (parsed.step) totalSteps = parsed.step
            } catch {
              // skip malformed data
            }
          }
        }

        const finalMsg: AgentStreamMessage = {
          ...assistantMsg,
          content: accumulated,
          toolCalls: toolCalls!.length > 0 ? toolCalls : undefined,
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
        const error = err instanceof Error ? err : new Error("Stream failed")
        setError(error)
        setAgentState("error")
        onError?.(error)
        setMessages((prev) => prev.filter((m) => m.id !== assistantMsg.id))
      } finally {
        setIsStreaming(false)
        abortRef.current = null
      }
    },
    [agentId, onError, onFinish],
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
