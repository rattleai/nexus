/**
 * useAgentConversation — orchestrates the multi-turn conversation lifecycle.
 *
 * Bridges the stream registry, instance stream hook, conversation store,
 * and backend session API into a single unified interface for the chat UI.
 */

import * as React from "react"
import { useRegistryStream, sendReply, getSessionId, abortStream } from "@/lib/agent-stream-registry"
import {
  useAgentConversationStore,
  type ConversationTurn,
  type ConversationStatus,
  type AgentToolCall,
} from "@/stores/agent-conversation-store"
import { useInstanceDetail } from "@/hooks/use-agents"

// ── Stream entry to conversation turn translation ────────

type AgentState = "idle" | "thinking" | "acting" | "complete" | "error"

interface UseAgentConversationResult {
  turns: ConversationTurn[]
  status: ConversationStatus
  agentState: AgentState
  isStreaming: boolean
  error?: string
  sendMessage: (content: string) => Promise<void>
  stop: () => void
}

export function useAgentConversation(
  instanceId: string,
  sessionId: string | null,
): UseAgentConversationResult {
  const store = useAgentConversationStore()
  const registry = useRegistryStream(instanceId)
  const { data: instance } = useInstanceDetail(instanceId)

  // Resolve sessionId: from prop, registry, or instance
  const resolvedSessionId = sessionId
    ?? getSessionId(instanceId)
    ?? instance?.session_id
    ?? null

  // Track the current assistant turn ID for streaming updates
  const assistantTurnIdRef = React.useRef<string | null>(null)
  const toolCallMapRef = React.useRef(new Map<string, string>()) // toolName → toolCallId
  const processedCountRef = React.useRef(0)
  const sendingRef = React.useRef(false)
  const streamVersionRef = React.useRef(0)

  // Initialize conversation in store
  React.useEffect(() => {
    if (!resolvedSessionId) return
    const defId = instance?.definition_id ?? ""
    store.initConversation(resolvedSessionId, defId)
  }, [resolvedSessionId, instance?.definition_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset processing state when session or instance changes
  React.useEffect(() => {
    processedCountRef.current = 0
    assistantTurnIdRef.current = null
    toolCallMapRef.current.clear()
  }, [resolvedSessionId, instanceId])

  // Process registry stream entries into conversation turns
  React.useEffect(() => {
    if (!resolvedSessionId || !registry.entries) return
    const currentVersion = streamVersionRef.current

    const entries = registry.entries
    const startIdx = processedCountRef.current

    for (let i = startIdx; i < entries.length; i++) {
      if (streamVersionRef.current !== currentVersion) return
      const entry = entries[i]

      switch (entry.type) {
        case "thinking": {
          if (!assistantTurnIdRef.current) {
            assistantTurnIdRef.current = store.startAssistantTurn(resolvedSessionId, instanceId)
          }
          store.addThinkingStep(resolvedSessionId, assistantTurnIdRef.current, {
            id: entry.id,
            content: entry.content,
            timestamp: entry.timestamp,
          })
          break
        }

        case "content": {
          if (!assistantTurnIdRef.current) {
            assistantTurnIdRef.current = store.startAssistantTurn(resolvedSessionId, instanceId)
          }
          // For content entries, we need to compute the delta since last process
          // The registry mutates content entries in-place (appending text)
          // So we track what we've already sent via the turn's content field
          const conv = store.conversations[resolvedSessionId]
          const turn = conv?.turns.find((t) => t.id === assistantTurnIdRef.current)
          const existingLength = turn?.content.length ?? 0
          if (entry.text.length > existingLength) {
            const delta = entry.text.slice(existingLength)
            store.appendContent(resolvedSessionId, assistantTurnIdRef.current, delta)
          }
          break
        }

        case "tool_call": {
          if (!assistantTurnIdRef.current) {
            assistantTurnIdRef.current = store.startAssistantTurn(resolvedSessionId, instanceId)
          }
          const toolCallId = entry.id
          toolCallMapRef.current.set(entry.toolName, toolCallId)
          const toolCall: AgentToolCall = {
            id: toolCallId,
            toolName: entry.toolName,
            args: entry.args,
            status: entry.status === "completed" ? "completed" : entry.status === "error" ? "error" : "running",
            result: entry.result,
            error: entry.error,
            durationMs: entry.durationMs,
          }
          store.addToolCall(resolvedSessionId, assistantTurnIdRef.current, toolCall)
          break
        }

        case "status": {
          if (entry.status === "completed" && assistantTurnIdRef.current) {
            store.completeTurn(resolvedSessionId, assistantTurnIdRef.current)
            assistantTurnIdRef.current = null
            toolCallMapRef.current.clear()
          } else if (entry.status === "failed" && assistantTurnIdRef.current) {
            store.errorTurn(
              resolvedSessionId,
              assistantTurnIdRef.current,
              entry.message ?? "An error occurred",
            )
            assistantTurnIdRef.current = null
          }
          break
        }

        // step entries are metadata — skip (tokens/cost tracked at turn level)
        case "step":
          break
      }
    }

    processedCountRef.current = entries.length

    // Also handle tool_call status updates (the registry mutates entries in-place)
    if (assistantTurnIdRef.current) {
      for (const entry of entries) {
        if (entry.type === "tool_call") {
          const existingId = toolCallMapRef.current.get(entry.toolName)
          if (existingId) {
            store.updateToolCall(resolvedSessionId, assistantTurnIdRef.current, existingId, {
              status: entry.status === "completed" ? "completed" : entry.status === "error" ? "error" : "running",
              result: entry.result,
              error: entry.error,
              durationMs: entry.durationMs,
            })
          }
        }
      }
    }
  }, [resolvedSessionId, instanceId, registry.entries, registry.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle stream completion
  React.useEffect(() => {
    if (!resolvedSessionId) return
    if (registry.status === "completed") {
      store.setStatus(resolvedSessionId, "awaiting-input")
    } else if (registry.status === "error") {
      store.setStatus(resolvedSessionId, "error")
    }
  }, [registry.status, resolvedSessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load history from completed instance if no stream exists
  React.useEffect(() => {
    if (!resolvedSessionId || !instance) return
    if (registry.hasStream) return // Active stream, don't load history
    if (store.conversations[resolvedSessionId]?.turns.length) return // Already have turns

    // Build turns from instance data
    const turns: ConversationTurn[] = []

    // User message
    const messages = Array.isArray(instance.input_data?.messages) ? instance.input_data.messages as Array<Record<string, unknown>> : null
    const prompt = instance.input_data?.prompt
      ?? (messages && messages.length > 0 ? messages[messages.length - 1]?.content : null)
      ?? JSON.stringify(instance.input_data)
    if (prompt) {
      turns.push({
        id: crypto.randomUUID(),
        role: "user",
        content: String(prompt),
        segments: [{ type: "content", text: String(prompt) }],
        thinkingSteps: [],
        status: "complete",
        instanceId,
        timestamp: new Date(instance.started_at ?? instance.created_at).getTime(),
      })
    }

    // Assistant response
    const output = instance.output_data?.output ?? instance.output_data
    if (output && typeof output === "string") {
      turns.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: output,
        segments: [{ type: "content", text: output }],
        thinkingSteps: [],
        status: "complete",
        instanceId,
        tokens: instance.tokens_used,
        cost: instance.cost_usd,
        timestamp: new Date(instance.completed_at ?? instance.created_at).getTime(),
      })
    }

    if (turns.length > 0) {
      store.loadHistory(resolvedSessionId, turns)
    }
  }, [resolvedSessionId, instanceId, instance, registry.hasStream]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Send message handler ─────────────────────────────

  const sendMessage = React.useCallback(
    async (content: string) => {
      // Capture at call time to prevent stale closure during async gap
      const sid = resolvedSessionId
      if (!sid || sendingRef.current) return
      sendingRef.current = true
      streamVersionRef.current += 1

      try {
        // Add user turn to store
        store.addUserTurn(sid, content, instanceId)

        // Reset processing state for new stream
        processedCountRef.current = 0
        assistantTurnIdRef.current = null
        toolCallMapRef.current.clear()

        store.setStatus(sid, "streaming")

        // Send reply to backend — this creates a new SSE stream in the registry
        const newInstanceId = await sendReply(sid, content)

        // Start assistant turn for the new stream
        assistantTurnIdRef.current = store.startAssistantTurn(sid, newInstanceId)
      } catch (err) {
        store.setStatus(sid, "error", err instanceof Error ? err.message : "Failed to send message")
      } finally {
        sendingRef.current = false
      }
    },
    [resolvedSessionId, instanceId], // eslint-disable-line react-hooks/exhaustive-deps
  )

  // ── Stop handler ──────────────────────────────────────

  const stop = React.useCallback(() => {
    if (registry.isActive) {
      abortStream(instanceId)
    }
  }, [instanceId, registry.isActive])

  // ── Derive agent state ────────────────────────────────

  const conversation = resolvedSessionId ? store.conversations[resolvedSessionId] : undefined

  let agentState: AgentState = "idle"
  if (registry.isActive) {
    // Check if agent is thinking or acting based on latest entries
    const entries = registry.entries ?? []
    const lastEntry = entries[entries.length - 1]
    if (lastEntry?.type === "thinking") {
      agentState = "thinking"
    } else if (lastEntry?.type === "tool_call" && lastEntry.status === "running") {
      agentState = "acting"
    } else {
      agentState = "thinking"
    }
  } else if (registry.status === "completed") {
    agentState = "complete"
  } else if (registry.status === "error") {
    agentState = "error"
  }

  return {
    turns: conversation?.turns ?? [],
    status: conversation?.status ?? "idle",
    agentState,
    isStreaming: registry.isActive,
    error: conversation?.error,
    sendMessage,
    stop,
  }
}
