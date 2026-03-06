import { create } from "zustand"
import { persist } from "zustand/middleware"

interface UIState {
  sidebarOpen: boolean
  commandPaletteOpen: boolean
  sheetOpen: boolean
  activePanel: string | null

  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  setCommandPaletteOpen: (open: boolean) => void
  setSheetOpen: (open: boolean) => void
  setActivePanel: (panel: string | null) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      commandPaletteOpen: false,
      sheetOpen: false,
      activePanel: null,

      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setSheetOpen: (open) => set({ sheetOpen: open }),
      setActivePanel: (panel) => set({ activePanel: panel }),
    }),
    { name: "ui-store", partialize: (s) => ({ sidebarOpen: s.sidebarOpen }) },
  ),
)
