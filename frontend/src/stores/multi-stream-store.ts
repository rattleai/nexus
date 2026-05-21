import { create } from "zustand"
import type { AgentStreamMessage } from "@/hooks/use-agent-stream"

export interface InstanceStreamState {
  instanceId: string
  definitionId: string
  agentName: string
  messages: AgentStreamMessage[]
  agentState: "idle" | "thinking" | "acting" | "complete" | "error"
  isStreaming: boolean
  error: string | null
  tokens: number
  cost: number
  steps: number
  scrollLocked: boolean
}

interface MultiStreamStore {
  streams: Record<string, InstanceStreamState>

  initStream: (instanceId: string, definitionId: string, agentName: string) => void
  appendMessage: (instanceId: string, message: AgentStreamMessage) => void
  updateStreamState: (instanceId: string, update: Partial<InstanceStreamState>) => void
  completeStream: (instanceId: string) => void
  errorStream: (instanceId: string, error: string) => void
  removeStream: (instanceId: string) => void
  toggleScrollLock: (instanceId: string) => void
}

export const useMultiStreamStore = create<MultiStreamStore>()((set) => ({
  streams: {},

  initStream: (instanceId, definitionId, agentName) =>
    set((s) => ({
      streams: {
        ...s.streams,
        [instanceId]: {
          instanceId,
          definitionId,
          agentName,
          messages: [],
          agentState: "idle",
          isStreaming: true,
          error: null,
          tokens: 0,
          cost: 0,
          steps: 0,
          scrollLocked: false,
        },
      },
    })),

  appendMessage: (instanceId, message) =>
    set((s) => {
      const stream = s.streams[instanceId]
      if (!stream) return s
      return {
        streams: {
          ...s.streams,
          [instanceId]: {
            ...stream,
            messages: [...stream.messages, message],
          },
        },
      }
    }),

  updateStreamState: (instanceId, update) =>
    set((s) => {
      const stream = s.streams[instanceId]
      if (!stream) return s
      return {
        streams: {
          ...s.streams,
          [instanceId]: { ...stream, ...update },
        },
      }
    }),

  completeStream: (instanceId) =>
    set((s) => {
      const stream = s.streams[instanceId]
      if (!stream) return s
      return {
        streams: {
          ...s.streams,
          [instanceId]: { ...stream, agentState: "complete", isStreaming: false },
        },
      }
    }),

  errorStream: (instanceId, error) =>
    set((s) => {
      const stream = s.streams[instanceId]
      if (!stream) return s
      return {
        streams: {
          ...s.streams,
          [instanceId]: { ...stream, agentState: "error", isStreaming: false, error },
        },
      }
    }),

  removeStream: (instanceId) =>
    set((s) => {
      const { [instanceId]: _, ...rest } = s.streams
      return { streams: rest }
    }),

  toggleScrollLock: (instanceId) =>
    set((s) => {
      const stream = s.streams[instanceId]
      if (!stream) return s
      return {
        streams: {
          ...s.streams,
          [instanceId]: { ...stream, scrollLocked: !stream.scrollLocked },
        },
      }
    }),
}))
