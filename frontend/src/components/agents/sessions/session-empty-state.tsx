import { Bot, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"

interface SessionEmptyStateProps {
  onNewRun?: () => void
}

export function SessionEmptyState({ onNewRun }: SessionEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-8">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-muted/50 mb-6">
        <Bot className="h-10 w-10 text-muted-foreground/50" />
      </div>
      <h2 className="text-lg font-semibold text-foreground">
        Select a session
      </h2>
      <p className="text-sm text-muted-foreground mt-1.5 max-w-xs">
        Choose a session from the sidebar to view its output, or start a new agent run.
      </p>
      {onNewRun && (
        <Button
          variant="outline"
          size="sm"
          className="mt-6"
          onClick={onNewRun}
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          New Run
        </Button>
      )}
    </div>
  )
}
