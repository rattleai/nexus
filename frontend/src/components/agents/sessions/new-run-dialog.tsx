import * as React from "react"
import { Loader2, Send } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { useAgentDefinitions } from "@/hooks/use-agents"
import { startConversation } from "@/lib/agent-stream-registry"

interface NewRunDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (instanceId: string, sessionId?: string) => void
  preselectedAgentId?: string
}

export function NewRunDialog({ open, onOpenChange, onCreated, preselectedAgentId }: NewRunDialogProps) {
  const [selectedAgentId, setSelectedAgentId] = React.useState<string>(preselectedAgentId ?? "")
  const [prompt, setPrompt] = React.useState("")
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const { data: definitionsData } = useAgentDefinitions("active")

  const agents = definitionsData?.items ?? []
  const selectedAgent = agents.find((a) => a.id === selectedAgentId)

  // Sync preselected agent when dialog opens
  React.useEffect(() => {
    if (open && preselectedAgentId) {
      setSelectedAgentId(preselectedAgentId)
    }
  }, [open, preselectedAgentId])

  const handleSubmit = async () => {
    if (!selectedAgentId || !prompt.trim() || isSubmitting) return
    setIsSubmitting(true)
    try {
      const { instanceId, sessionId } = await startConversation(selectedAgentId, prompt.trim())
      onOpenChange(false)
      setSelectedAgentId(preselectedAgentId ?? "")
      setPrompt("")
      onCreated?.(instanceId, sessionId)
    } catch {
      // Error shown via toast
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New Agent Run</DialogTitle>
          <DialogDescription>
            Select an agent and tell it what to do.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="agent-select">Agent</Label>
            <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger id="agent-select">
                <SelectValue placeholder="Select an agent..." />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    <div className="flex flex-col">
                      <span>{agent.name}</span>
                      {agent.description && (
                        <span className="text-xs text-muted-foreground">
                          {agent.description.slice(0, 50)}
                        </span>
                      )}
                    </div>
                  </SelectItem>
                ))}
                {agents.length === 0 && (
                  <div className="px-2 py-4 text-center text-sm text-muted-foreground">
                    No active agents found
                  </div>
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="prompt">
              Message
            </Label>
            <Textarea
              id="prompt"
              placeholder={
                selectedAgent
                  ? `Tell ${selectedAgent.name} what to do...`
                  : "What should the agent do?"
              }
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={3}
              className="text-sm resize-none"
            />
            <p className="text-[11px] text-muted-foreground">
              Shift+Enter for new line
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={!selectedAgentId || !prompt.trim() || isSubmitting}
          >
            {isSubmitting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="mr-1.5 h-3.5 w-3.5" />
            )}
            Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
