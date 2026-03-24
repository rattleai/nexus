import { create } from "zustand"
import { persist } from "zustand/middleware"

type AgentTab = "overview" | "chat" | "config" | "governance" | "runs" | "operations"

interface AgentWorkspaceState {
  selectedAgentId: string | null
  activeTab: AgentTab
  searchQuery: string
  statusFilter: "all" | "draft" | "active" | "disabled"
  recentAgentIds: string[]
  pendingMessage: string | null

  selectAgent: (id: string | null) => void
  setActiveTab: (tab: AgentTab) => void
  setSearchQuery: (query: string) => void
  setStatusFilter: (filter: "all" | "draft" | "active" | "disabled") => void
  addRecentAgent: (id: string) => void
  setPendingMessage: (msg: string | null) => void
  consumePendingMessage: () => string | null
}

const MAX_RECENT = 10

export type { AgentTab }

export const useAgentStore = create<AgentWorkspaceState>()(
  persist(
    (set, get) => ({
      selectedAgentId: null,
      activeTab: "overview",
      searchQuery: "",
      statusFilter: "all",
      recentAgentIds: [],
      pendingMessage: null,

      selectAgent: (id) =>
        set({
          selectedAgentId: id,
          activeTab: "overview",
        }),

      setActiveTab: (tab) => set({ activeTab: tab }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setStatusFilter: (filter) => set({ statusFilter: filter }),

      addRecentAgent: (id) =>
        set((s) => {
          const filtered = s.recentAgentIds.filter((r) => r !== id)
          return {
            recentAgentIds: [id, ...filtered].slice(0, MAX_RECENT),
          }
        }),

      setPendingMessage: (msg) => set({ pendingMessage: msg }),

      consumePendingMessage: () => {
        const msg = get().pendingMessage
        if (msg) set({ pendingMessage: null })
        return msg
      },
    }),
    {
      name: "agent-workspace",
      partialize: (s) => ({
        selectedAgentId: s.selectedAgentId,
        activeTab: s.activeTab,
        statusFilter: s.statusFilter,
        recentAgentIds: s.recentAgentIds,
      }),
    },
  ),
)
