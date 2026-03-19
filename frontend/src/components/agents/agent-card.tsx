import {
  Bot,
  MoreHorizontal,
  Play,
  Settings,
  Trash2,
  MessageSquare,
  Clock,
  Cpu,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import type { AgentDefinition } from "@/types/agents"

interface AgentCardProps {
  agent: AgentDefinition
  isSelected: boolean
  onSelect: () => void
  onChat: () => void
  onConfigure: () => void
  onDelete: () => void
}

const statusStyles: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; label: string }> = {
  active: { variant: "default", label: "Active" },
  draft: { variant: "secondary", label: "Draft" },
  disabled: { variant: "destructive", label: "Disabled" },
}

export function AgentCard({
  agent,
  isSelected,
  onSelect,
  onChat,
  onConfigure,
  onDelete,
}: AgentCardProps) {
  const status = statusStyles[agent.status] ?? statusStyles.draft

  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-left rounded-lg border p-3 transition-all duration-150",
        "hover:bg-accent/50 hover:border-accent-foreground/20",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isSelected &&
          "bg-accent border-primary/30 shadow-sm ring-1 ring-primary/20",
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            agent.status === "active"
              ? "bg-primary/10 text-primary"
              : agent.status === "draft"
                ? "bg-muted text-muted-foreground"
                : "bg-destructive/10 text-destructive",
          )}
        >
          <Bot className="h-4.5 w-4.5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{agent.name}</span>
            <Badge variant={status.variant} className="text-[10px] h-4.5 px-1.5 shrink-0">
              {status.label}
            </Badge>
          </div>
          {agent.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
              {agent.description}
            </p>
          )}
          <div className="flex items-center gap-3 mt-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {agent.model}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              v{agent.version}
            </span>
            {agent.allowed_tools.length > 0 && (
              <span className="flex items-center gap-1">
                {agent.allowed_tools.length} tools
              </span>
            )}
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation()
                onChat()
              }}
            >
              <MessageSquare className="mr-2 h-3.5 w-3.5" />
              Chat
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation()
                onConfigure()
              }}
            >
              <Settings className="mr-2 h-3.5 w-3.5" />
              Configure
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
            >
              <Trash2 className="mr-2 h-3.5 w-3.5" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </button>
  )
}
