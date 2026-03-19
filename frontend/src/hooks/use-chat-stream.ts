import * as React from "react"
import { getAccessToken } from "@/lib/api-client"

export interface ChatStreamMessage {
  id: string
  role: "user" | "assistant"
  content: string
  usage?: { inputTokens: number; outputTokens: number; totalTokens: number }
  toolCalls?: Array<{
    id: string
    name: string
    arguments: Record<string, unknown>
  }>
}

interface UseChatStreamOptions {
  apiUrl: string
  model?: string
  systemPrompt?: string
  onError?: (error: Error) => void
  onFinish?: (message: ChatStreamMessage) => void
}

export function useChatStream({
  apiUrl,
  model,
  systemPrompt,
  onError,
  onFinish,
}: UseChatStreamOptions) {
  const [messages, setMessages] = React.useState<ChatStreamMessage[]>([])
  const [isStreaming, setIsStreaming] = React.useState(false)
  const [error, setError] = React.useState<Error | null>(null)
  const abortControllerRef = React.useRef<AbortController | null>(null)
  const messagesRef = React.useRef(messages)
  messagesRef.current = messages

  // Abort on unmount
  React.useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
      abortControllerRef.current = null
    }
  }, [])

  const stop = React.useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsStreaming(false)
  }, [])

  const sendMessage = React.useCallback(
    async (content: string) => {
      setError(null)

      const userMessage: ChatStreamMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
      }

      const assistantMessage: ChatStreamMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
      }

      // Read current messages via ref to avoid stale closure
      const currentMessages = messagesRef.current

      setMessages((prev) => [...prev, userMessage, assistantMessage])
      setIsStreaming(true)

      const controller = new AbortController()
      abortControllerRef.current = controller

      try {
        const headers: Record<string, string> = { "Content-Type": "application/json" }
        const token = getAccessToken()
        if (token) headers["Authorization"] = `Bearer ${token}`

        const response = await fetch(apiUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({
            messages: [
              ...currentMessages.map((m) => ({ role: m.role, content: m.content })),
              { role: "user", content },
            ],
            model,
            systemPrompt,
            stream: true,
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          let errorMessage = `HTTP ${response.status}: ${response.statusText}`
          try {
            const errBody = await response.json()
            if (errBody.detail) errorMessage = errBody.detail
          } catch { /* use default */ }
          throw new Error(errorMessage)
        }

        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error("Response body is not readable")
        }

        const decoder = new TextDecoder()
        let accumulated = ""
        let usage: ChatStreamMessage["usage"] | undefined
        let toolCalls: ChatStreamMessage["toolCalls"] | undefined
        let lineBuffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          lineBuffer += chunk
          const lines = lineBuffer.split("\n")
          // Keep the last potentially incomplete line in the buffer
          lineBuffer = lines.pop() ?? ""

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue
            const data = line.slice(6).trim()
            if (data === "[DONE]") continue

            try {
              const parsed = JSON.parse(data)

              if (parsed.content) {
                accumulated += parsed.content
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? { ...m, content: accumulated }
                      : m,
                  ),
                )
              }

              if (parsed.usage) {
                usage = parsed.usage
              }

              if (parsed.tool_calls) {
                toolCalls = parsed.tool_calls
              }
            } catch {
              // Skip malformed SSE data
            }
          }
        }

        const finalMessage: ChatStreamMessage = {
          ...assistantMessage,
          content: accumulated,
          usage,
          toolCalls,
        }

        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMessage.id ? finalMessage : m)),
        )

        onFinish?.(finalMessage)
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return
        }
        const error =
          err instanceof Error ? err : new Error("Stream failed")
        setError(error)
        onError?.(error)

        // Remove the empty assistant message on error
        setMessages((prev) =>
          prev.filter((m) => m.id !== assistantMessage.id),
        )
      } finally {
        setIsStreaming(false)
        abortControllerRef.current = null
      }
    },
    [apiUrl, model, systemPrompt, onError, onFinish],
  )

  const reload = React.useCallback(async () => {
    // Read latest messages via ref to avoid stale closure
    const currentMessages = messagesRef.current
    const lastUserMessage = [...currentMessages]
      .reverse()
      .find((m) => m.role === "user")
    if (!lastUserMessage) return

    // Remove last assistant message and the user message
    setMessages((prev) => {
      const lastUserIdx = prev.findLastIndex((m: ChatStreamMessage) => m.role === "user")
      if (lastUserIdx === -1) return prev
      return prev.slice(0, lastUserIdx)
    })

    // Wait for state to settle before sending
    // Use a microtask to ensure the setMessages above is processed
    await new Promise((resolve) => setTimeout(resolve, 0))

    await sendMessage(lastUserMessage.content)
  }, [sendMessage])

  return {
    messages,
    sendMessage,
    isStreaming,
    error,
    stop,
    reload,
    setMessages,
  }
}
