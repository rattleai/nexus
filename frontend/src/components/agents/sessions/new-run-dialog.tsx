import * as React from "react"
import { Loader2, Play } from "lucide-react"
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
import { useAgentDefinitions, useRunAgent } from "@/hooks/use-agents"

interface NewRunDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (instanceId: string) => void
}

export function NewRunDialog({ open, onOpenChange, onCreated }: NewRunDialogProps) {
  const [selectedAgentId, setSelectedAgentId] = React.useState<string>("")
  const [inputData, setInputData] = React.useState("")
  const { data: definitionsData } = useAgentDefinitions("active")
  const runAgent = useRunAgent()

  const agents = definitionsData?.items ?? []

  const handleSubmit = () => {
    if (!selectedAgentId) return

    let parsedInput: Record<string, unknown> = {}
    if (inputData.trim()) {
      try {
        parsedInput = JSON.parse(inputData)
      } catch {
        parsedInput = { message: inputData }
      }
    }

    runAgent.mutate(
      { agentId: selectedAgentId, input: parsedInput },
      {
        onSuccess: (instance) => {
          onOpenChange(false)
          setSelectedAgentId("")
          setInputData("")
          onCreated?.(instance.id)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New Agent Run</DialogTitle>
          <DialogDescription>
            Select an agent and optionally provide input data.
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
            <Label htmlFor="input-data">Input (optional)</Label>
            <Textarea
              id="input-data"
              placeholder='JSON or plain text, e.g. {"task": "analyze data"}'
              value={inputData}
              onChange={(e) => setInputData(e.target.value)}
              rows={3}
              className="font-mono text-sm"
            />
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
            onClick={handleSubmit}
            disabled={!selectedAgentId || runAgent.isPending}
          >
            {runAgent.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1.5 h-3.5 w-3.5" />
            )}
            Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
