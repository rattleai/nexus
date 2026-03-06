import { create } from "zustand"
import { persist } from "zustand/middleware"

// ── Types ────────────────────────────────────────────

export type MessageRole = "user" | "assistant" | "system"

export type MessageStatus = "sending" | "streaming" | "complete" | "error"

export interface ChatMessage {
  id: string
  conversationId: string
  role: MessageRole
  content: string
  status: MessageStatus
  model: string | null
  tokenCount: number | null
  createdAt: string
  updatedAt: string
}

export interface Conversation {
  id: string
  title: string
  model: string
  pinned: boolean
  messageCount: number
  lastMessageAt: string | null
  createdAt: string
  updatedAt: string
}

export interface MessageDraft {
  conversationId: string
  content: string
}

// ── Constants ───────────────────────────────────────

const MAX_CONVERSATIONS = 100
const MAX_MESSAGES_PER_CONVERSATION = 500

// ── State ────────────────────────────────────────────

interface ChatState {
  conversations: Conversation[]
  messages: Record<string, ChatMessage[]>
  activeConversationId: string | null
  selectedModel: string
  streaming: boolean
  drafts: Record<string, string>

  createConversation: (title?: string) => string
  deleteConversation: (id: string) => void
  setActiveConversation: (id: string | null) => void
  addMessage: (
    conversationId: string,
    message: Omit<ChatMessage, "id" | "createdAt" | "updatedAt">,
  ) => string
  updateMessage: (
    conversationId: string,
    messageId: string,
    updates: Partial<Pick<ChatMessage, "content" | "status" | "tokenCount">>,
  ) => void
  setModel: (model: string) => void
  setStreaming: (streaming: boolean) => void
  updateDraft: (conversationId: string, content: string) => void
  pinConversation: (id: string) => void
  searchConversations: (query: string) => Conversation[]
}

const generateId = () => crypto.randomUUID()

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      conversations: [],
      messages: {},
      activeConversationId: null,
      selectedModel: "gpt-4o",
      streaming: false,
      drafts: {},

      createConversation: (title?: string) => {
        const id = generateId()
        const now = new Date().toISOString()
        const conversation: Conversation = {
          id,
          title: title ?? "New Conversation",
          model: get().selectedModel,
          pinned: false,
          messageCount: 0,
          lastMessageAt: null,
          createdAt: now,
          updatedAt: now,
        }
        set((s) => ({
          conversations: [conversation, ...s.conversations],
          messages: { ...s.messages, [id]: [] },
          activeConversationId: id,
        }))
        return id
      },

      deleteConversation: (id) =>
        set((s) => {
          const { [id]: _, ...remainingMessages } = s.messages
          const { [id]: __, ...remainingDrafts } = s.drafts
          const conversations = s.conversations.filter((c) => c.id !== id)
          return {
            conversations,
            messages: remainingMessages,
            drafts: remainingDrafts,
            activeConversationId:
              s.activeConversationId === id
                ? (conversations[0]?.id ?? null)
                : s.activeConversationId,
          }
        }),

      setActiveConversation: (id) => set({ activeConversationId: id }),

      addMessage: (conversationId, message) => {
        const id = generateId()
        const now = new Date().toISOString()
        const fullMessage: ChatMessage = {
          ...message,
          id,
          createdAt: now,
          updatedAt: now,
        }
        set((s) => {
          const existing = s.messages[conversationId] ?? []
          return {
            messages: {
              ...s.messages,
              [conversationId]: [...existing, fullMessage],
            },
            conversations: s.conversations.map((c) =>
              c.id === conversationId
                ? {
                    ...c,
                    messageCount: c.messageCount + 1,
                    lastMessageAt: now,
                    updatedAt: now,
                  }
                : c,
            ),
          }
        })
        return id
      },

      updateMessage: (conversationId, messageId, updates) =>
        set((s) => {
          const msgs = s.messages[conversationId]
          if (!msgs) return s
          return {
            messages: {
              ...s.messages,
              [conversationId]: msgs.map((m) =>
                m.id === messageId
                  ? { ...m, ...updates, updatedAt: new Date().toISOString() }
                  : m,
              ),
            },
          }
        }),

      setModel: (model) => set({ selectedModel: model }),

      setStreaming: (streaming) => set({ streaming }),

      updateDraft: (conversationId, content) =>
        set((s) => ({
          drafts: { ...s.drafts, [conversationId]: content },
        })),

      pinConversation: (id) =>
        set((s) => ({
          conversations: s.conversations.map((c) =>
            c.id === id ? { ...c, pinned: !c.pinned } : c,
          ),
        })),

      searchConversations: (query) => {
        const lower = query.toLowerCase()
        return get().conversations.filter((c) =>
          c.title.toLowerCase().includes(lower),
        )
      },
    }),
    {
      name: "chat-store",
      partialize: (s) => {
        // Limit persisted data to prevent unbounded localStorage growth
        const conversations = s.conversations.slice(0, MAX_CONVERSATIONS)
        const conversationIds = new Set(conversations.map((c) => c.id))

        const messages: Record<string, ChatMessage[]> = {}
        for (const [id, msgs] of Object.entries(s.messages)) {
          if (conversationIds.has(id)) {
            messages[id] = msgs.slice(-MAX_MESSAGES_PER_CONVERSATION)
          }
        }

        const drafts: Record<string, string> = {}
        for (const [id, draft] of Object.entries(s.drafts)) {
          if (conversationIds.has(id)) {
            drafts[id] = draft
          }
        }

        return {
          conversations,
          messages,
          activeConversationId: s.activeConversationId,
          selectedModel: s.selectedModel,
          drafts,
        }
      },
    },
  ),
)
