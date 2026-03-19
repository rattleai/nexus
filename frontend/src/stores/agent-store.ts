import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { AgentDefinition } from "@/types/agents"

type AgentTab = "overview" | "chat" | "config" | "governance" | "runs"

interface AgentWorkspaceState {
  selectedAgentId: string | null
  activeTab: AgentTab
  searchQuery: string
  statusFilter: "all" | "draft" | "active" | "disabled"
  commandPaletteOpen: boolean
  agentPaletteOpen: boolean
  recentAgentIds: string[]

  selectAgent: (id: string | null) => void
  setActiveTab: (tab: AgentTab) => void
  setSearchQuery: (query: string) => void
  setStatusFilter: (filter: "all" | "draft" | "active" | "disabled") => void
  setCommandPaletteOpen: (open: boolean) => void
  setAgentPaletteOpen: (open: boolean) => void
  addRecentAgent: (id: string) => void
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
      commandPaletteOpen: false,
      agentPaletteOpen: false,
      recentAgentIds: [],

      selectAgent: (id) =>
        set({
          selectedAgentId: id,
          activeTab: "overview",
        }),

      setActiveTab: (tab) => set({ activeTab: tab }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setStatusFilter: (filter) => set({ statusFilter: filter }),
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setAgentPaletteOpen: (open) => set({ agentPaletteOpen: open }),

      addRecentAgent: (id) =>
        set((s) => {
          const filtered = s.recentAgentIds.filter((r) => r !== id)
          return {
            recentAgentIds: [id, ...filtered].slice(0, MAX_RECENT),
          }
        }),
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
