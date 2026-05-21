import { Bot, User } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ConversationTurn } from "@/stores/agent-conversation-store"
import { AssistantMessage } from "./assistant-message"

interface AgentChatMessageProps {
  turn: ConversationTurn
  className?: string
}

export function AgentChatMessage({ turn, className }: AgentChatMessageProps) {
  if (turn.role === "system") {
    return (
      <div className={cn("flex justify-center py-2", className)}>
        <span className="text-xs text-muted-foreground bg-muted px-3 py-1 rounded-full">
          {turn.content}
        </span>
      </div>
    )
  }

  if (turn.role === "user") {
    return (
      <div className={cn("flex items-start gap-3 justify-end", className)}>
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground">
          <p className="text-sm whitespace-pre-wrap">{turn.content}</p>
        </div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
          <User className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
    )
  }

  // Assistant
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
        <Bot className="h-4 w-4 text-primary" />
      </div>
      <div className="max-w-[85%] min-w-0">
        <AssistantMessage turn={turn} />
        {/* Turn metrics */}
        {turn.status === "complete" && (turn.tokens || turn.cost) && (
          <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground">
            {turn.tokens != null && <span>{turn.tokens.toLocaleString()} tokens</span>}
            {turn.cost != null && <span>${turn.cost.toFixed(4)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
