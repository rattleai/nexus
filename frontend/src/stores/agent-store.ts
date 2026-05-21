import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { WorkspaceMode, StreamPaneState } from "@/types/agents"

type AgentTab = "overview" | "config" | "governance" | "runs" | "operations"

interface AgentWorkspaceState {
  selectedAgentId: string | null
  activeTab: AgentTab
  searchQuery: string
  statusFilter: "all" | "draft" | "active" | "disabled"
  recentAgentIds: string[]
  pendingMessage: string | null

  // Multi-agent workspace
  workspaceMode: WorkspaceMode
  streamPanes: StreamPaneState[]
  focusedPaneId: string | null
  instanceMonitorCollapsed: boolean
  pinnedInstanceIds: string[]
  drawerInstanceId: string | null

  selectAgent: (id: string | null) => void
  setActiveTab: (tab: AgentTab) => void
  setSearchQuery: (query: string) => void
  setStatusFilter: (filter: "all" | "draft" | "active" | "disabled") => void
  addRecentAgent: (id: string) => void
  setPendingMessage: (msg: string | null) => void
  consumePendingMessage: () => string | null

  // Multi-agent workspace actions
  setWorkspaceMode: (mode: WorkspaceMode) => void
  addStreamPane: (instanceId: string, agentName: string, definitionId: string) => void
  addEmptyStreamPane: () => void
  removeStreamPane: (paneId: string) => void
  focusPane: (paneId: string) => void
  assignInstanceToPane: (paneId: string, instanceId: string) => void
  toggleMonitorCollapsed: () => void
  pinInstance: (instanceId: string) => void
  unpinInstance: (instanceId: string) => void
  openDrawer: (instanceId: string) => void
  closeDrawer: () => void
}

const MAX_RECENT = 10
const MAX_PANES = 3

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

      // Multi-agent workspace defaults
      workspaceMode: "single",
      streamPanes: [],
      focusedPaneId: null,
      instanceMonitorCollapsed: false,
      pinnedInstanceIds: [],
      drawerInstanceId: null,

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

      // Multi-agent workspace actions
      setWorkspaceMode: (mode) => set({ workspaceMode: mode }),

      addStreamPane: (instanceId, agentName, definitionId) =>
        set((s) => {
          if (s.streamPanes.length >= MAX_PANES) return s
          // Don't add duplicate instances
          if (s.streamPanes.some((p) => p.instanceId === instanceId)) {
            return { focusedPaneId: s.streamPanes.find((p) => p.instanceId === instanceId)!.paneId }
          }
          const paneId = crypto.randomUUID()
          return {
            streamPanes: [...s.streamPanes, { paneId, instanceId, agentName, definitionId }],
            focusedPaneId: paneId,
            workspaceMode: "multi-stream",
          }
        }),

      addEmptyStreamPane: () =>
        set((s) => {
          if (s.streamPanes.length >= MAX_PANES) return s
          const paneId = crypto.randomUUID()
          return {
            streamPanes: [...s.streamPanes, { paneId, instanceId: null, agentName: "Unassigned", definitionId: "" }],
            focusedPaneId: paneId,
            workspaceMode: "multi-stream",
          }
        }),

      removeStreamPane: (paneId) =>
        set((s) => {
          const panes = s.streamPanes.filter((p) => p.paneId !== paneId)
          return {
            streamPanes: panes,
            focusedPaneId: s.focusedPaneId === paneId ? (panes[0]?.paneId ?? null) : s.focusedPaneId,
          }
        }),

      focusPane: (paneId) => set({ focusedPaneId: paneId }),

      assignInstanceToPane: (paneId, instanceId) =>
        set((s) => ({
          streamPanes: s.streamPanes.map((p) =>
            p.paneId === paneId ? { ...p, instanceId } : p,
          ),
        })),

      toggleMonitorCollapsed: () =>
        set((s) => ({ instanceMonitorCollapsed: !s.instanceMonitorCollapsed })),

      pinInstance: (instanceId) =>
        set((s) => ({
          pinnedInstanceIds: s.pinnedInstanceIds.includes(instanceId)
            ? s.pinnedInstanceIds
            : [...s.pinnedInstanceIds, instanceId],
        })),

      unpinInstance: (instanceId) =>
        set((s) => ({
          pinnedInstanceIds: s.pinnedInstanceIds.filter((id) => id !== instanceId),
        })),

      openDrawer: (instanceId) => set({ drawerInstanceId: instanceId }),
      closeDrawer: () => set({ drawerInstanceId: null }),
    }),
    {
      name: "agent-workspace",
      partialize: (s) => ({
        selectedAgentId: s.selectedAgentId,
        activeTab: s.activeTab,
        statusFilter: s.statusFilter,
        recentAgentIds: s.recentAgentIds,
        workspaceMode: s.workspaceMode,
        pinnedInstanceIds: s.pinnedInstanceIds,
        instanceMonitorCollapsed: s.instanceMonitorCollapsed,
      }),
    },
  ),
)
