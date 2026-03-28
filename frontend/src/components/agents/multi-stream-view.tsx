import * as React from "react"
import { Plus, Columns3 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable"
import { useAgentStore } from "@/stores/agent-store"
import { StreamPane } from "@/components/agents/stream-pane"

const MAX_PANES = 3

export function MultiStreamView() {
  const streamPanes = useAgentStore((s) => s.streamPanes)
  const focusedPaneId = useAgentStore((s) => s.focusedPaneId)
  const addEmptyStreamPane = useAgentStore((s) => s.addEmptyStreamPane)
  const focusPane = useAgentStore((s) => s.focusPane)

  // Keyboard: Tab cycles focus between panes
  React.useEffect(() => {
    if (streamPanes.length < 2) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle Tab when not in an input/textarea/select
      if (
        e.key !== "Tab" ||
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return
      }

      const currentIndex = streamPanes.findIndex((p) => p.paneId === focusedPaneId)
      if (currentIndex === -1) return

      e.preventDefault()
      const nextIndex = e.shiftKey
        ? (currentIndex - 1 + streamPanes.length) % streamPanes.length
        : (currentIndex + 1) % streamPanes.length

      focusPane(streamPanes[nextIndex].paneId)
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [streamPanes, focusedPaneId, focusPane])

  // ── Empty state ─────────────────────────────────────────────────

  if (streamPanes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary mb-4">
          <Columns3 className="h-8 w-8" />
        </div>
        <h3 className="text-lg font-semibold mb-1">Multi-Stream Workspace</h3>
        <p className="text-sm text-muted-foreground max-w-md mb-6">
          Launch an agent or open a running instance to start streaming. You can
          observe up to {MAX_PANES} agent instances side by side.
        </p>
        <Button onClick={addEmptyStreamPane}>
          <Plus className="mr-1.5 h-4 w-4" />
          Add First Pane
        </Button>
      </div>
    )
  }

  // ── Panel layout ────────────────────────────────────────────────

  // Calculate default/min sizes based on pane count
  const defaultSize = Math.floor(100 / streamPanes.length)
  const minSize = streamPanes.length >= 3 ? 20 : 25

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-2 py-1.5 border-b">
        <div className="flex items-center gap-2">
          <Columns3 className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            {streamPanes.length} {streamPanes.length === 1 ? "Pane" : "Panes"}
          </span>
        </div>
        {streamPanes.length < MAX_PANES && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={addEmptyStreamPane}
          >
            <Plus className="mr-1 h-3 w-3" />
            Add Pane
          </Button>
        )}
      </div>

      {/* Resizable panels */}
      <div className="flex-1 min-h-0 p-1.5">
        <ResizablePanelGroup orientation="horizontal" className="h-full">
          {streamPanes.map((pane, index) => (
            <React.Fragment key={pane.paneId}>
              {index > 0 && <ResizableHandle withHandle />}
              <ResizablePanel defaultSize={defaultSize} minSize={minSize}>
                <div className="h-full p-1">
                  <StreamPane
                    instanceId={pane.instanceId}
                    agentName={pane.agentName}
                    paneId={pane.paneId}
                    isFocused={pane.paneId === focusedPaneId}
                  />
                </div>
              </ResizablePanel>
            </React.Fragment>
          ))}
        </ResizablePanelGroup>
      </div>
    </div>
  )
}
