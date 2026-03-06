"use client"

import * as React from "react"

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

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
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

  const stop = React.useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsStreaming(false)
  }, [])

  const sendMessage = React.useCallback(
    async (content: string) => {
      setError(null)

      const userMessage: ChatStreamMessage = {
        id: generateId(),
        role: "user",
        content,
      }

      const assistantMessage: ChatStreamMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
      }

      setMessages((prev) => [...prev, userMessage, assistantMessage])
      setIsStreaming(true)

      const controller = new AbortController()
      abortControllerRef.current = controller

      try {
        const response = await fetch(apiUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: [
              ...messages.map((m) => ({ role: m.role, content: m.content })),
              { role: "user", content },
            ],
            model,
            systemPrompt,
            stream: true,
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error("Response body is not readable")
        }

        const decoder = new TextDecoder()
        let accumulated = ""
        let usage: ChatStreamMessage["usage"] | undefined
        let toolCalls: ChatStreamMessage["toolCalls"] | undefined

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          const lines = chunk.split("\n")

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
    [apiUrl, model, systemPrompt, messages, onError, onFinish],
  )

  const reload = React.useCallback(async () => {
    const lastUserMessage = [...messages]
      .reverse()
      .find((m) => m.role === "user")
    if (!lastUserMessage) return

    // Remove last assistant message and the user message
    setMessages((prev) => {
      const lastUserIdx = prev.findLastIndex((m) => m.role === "user")
      if (lastUserIdx === -1) return prev
      return prev.slice(0, lastUserIdx)
    })

    await sendMessage(lastUserMessage.content)
  }, [messages, sendMessage])

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
