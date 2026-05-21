/**
 * Agent Conversation Store — manages per-session conversation state
 * for interactive multi-turn agent runs.
 *
 * NOT localStorage-persisted: the backend (session.messages) is the
 * source of truth for completed conversations. This store only holds
 * ephemeral/in-progress state.
 */

import { create } from "zustand"

// ── Types ──────────────────────────────────────────────

export interface AgentToolCall {
  id: string
  toolName: string
  args: Record<string, unknown>
  status: "pending" | "running" | "completed" | "error"
  result?: unknown
  error?: string
  durationMs?: number
}

export interface ThinkingStep {
  id: string
  content: string
  timestamp: number
}

export type TurnSegment =
  | { type: "content"; text: string }
  | { type: "tool_call"; toolCall: AgentToolCall }

export interface ConversationTurn {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  segments: TurnSegment[]
  thinkingSteps: ThinkingStep[]
  status: "complete" | "streaming" | "error"
  instanceId: string
  tokens?: number
  cost?: number
  timestamp: number
}

export type ConversationStatus = "idle" | "streaming" | "awaiting-input" | "error"

export interface SessionConversation {
  sessionId: string
  definitionId: string
  turns: ConversationTurn[]
  status: ConversationStatus
  error?: string
}

// ── Store ──────────────────────────────────────────────

interface AgentConversationState {
  conversations: Record<string, SessionConversation>

  // Initialization
  initConversation: (sessionId: string, definitionId: string) => void

  // Turn management
  addUserTurn: (sessionId: string, content: string, instanceId: string) => string
  startAssistantTurn: (sessionId: string, instanceId: string) => string

  // Streaming updates within the current assistant turn
  appendContent: (sessionId: string, turnId: string, delta: string) => void
  addThinkingStep: (sessionId: string, turnId: string, step: ThinkingStep) => void
  addToolCall: (sessionId: string, turnId: string, toolCall: AgentToolCall) => void
  updateToolCall: (
    sessionId: string,
    turnId: string,
    toolCallId: string,
    update: Partial<AgentToolCall>,
  ) => void

  // Turn completion
  completeTurn: (sessionId: string, turnId: string, data?: { tokens?: number; cost?: number }) => void
  errorTurn: (sessionId: string, turnId: string, error: string) => void

  // Conversation status
  setStatus: (sessionId: string, status: ConversationStatus, error?: string) => void

  // Load history from backend
  loadHistory: (sessionId: string, turns: ConversationTurn[]) => void

  // Cleanup
  removeConversation: (sessionId: string) => void
}

export const useAgentConversationStore = create<AgentConversationState>((set) => ({
  conversations: {},

  initConversation: (sessionId, definitionId) =>
    set((state) => {
      if (state.conversations[sessionId]) return state
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: {
            sessionId,
            definitionId,
            turns: [],
            status: "idle",
          },
        },
      }
    }),

  addUserTurn: (sessionId, content, instanceId) => {
    const turnId = crypto.randomUUID()
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: {
            ...conv,
            turns: [
              ...conv.turns,
              {
                id: turnId,
                role: "user",
                content,
                segments: [{ type: "content", text: content }],
                thinkingSteps: [],
                status: "complete",
                instanceId,
                timestamp: Date.now(),
              },
            ],
          },
        },
      }
    })
    return turnId
  },

  startAssistantTurn: (sessionId, instanceId) => {
    const turnId = crypto.randomUUID()
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: {
            ...conv,
            status: "streaming",
            turns: [
              ...conv.turns,
              {
                id: turnId,
                role: "assistant",
                content: "",
                segments: [],
                thinkingSteps: [],
                status: "streaming",
                instanceId,
                timestamp: Date.now(),
              },
            ],
          },
        },
      }
    })
    return turnId
  },

  appendContent: (sessionId, turnId, delta) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        const segments = [...t.segments]
        const last = segments[segments.length - 1]
        if (last && last.type === "content") {
          segments[segments.length - 1] = { type: "content", text: last.text + delta }
        } else {
          segments.push({ type: "content", text: delta })
        }
        return { ...t, content: t.content + delta, segments }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns },
        },
      }
    }),

  addThinkingStep: (sessionId, turnId, step) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        return { ...t, thinkingSteps: [...t.thinkingSteps, step] }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns },
        },
      }
    }),

  addToolCall: (sessionId, turnId, toolCall) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        return {
          ...t,
          segments: [...t.segments, { type: "tool_call" as const, toolCall }],
        }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns },
        },
      }
    }),

  updateToolCall: (sessionId, turnId, toolCallId, update) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        const segments = t.segments.map((s) => {
          if (s.type !== "tool_call" || s.toolCall.id !== toolCallId) return s
          return { ...s, toolCall: { ...s.toolCall, ...update } }
        })
        return { ...t, segments }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns },
        },
      }
    }),

  completeTurn: (sessionId, turnId, data) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        return {
          ...t,
          status: "complete" as const,
          tokens: data?.tokens ?? t.tokens,
          cost: data?.cost ?? t.cost,
        }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns, status: "awaiting-input" },
        },
      }
    }),

  errorTurn: (sessionId, turnId, error) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      const turns = conv.turns.map((t) => {
        if (t.id !== turnId) return t
        return { ...t, status: "error" as const, content: t.content || error }
      })
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns, status: "error", error },
        },
      }
    }),

  setStatus: (sessionId, status, error) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, status, error },
        },
      }
    }),

  loadHistory: (sessionId, turns) =>
    set((state) => {
      const conv = state.conversations[sessionId]
      if (!conv) return state
      return {
        conversations: {
          ...state.conversations,
          [sessionId]: { ...conv, turns, status: "awaiting-input" },
        },
      }
    }),

  removeConversation: (sessionId) =>
    set((state) => {
      const { [sessionId]: _, ...rest } = state.conversations
      return { conversations: rest }
    }),
}))
