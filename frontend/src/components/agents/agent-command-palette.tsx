import * as React from "react"
import {
  Bot,
  MessageSquare,
  Plus,
} from "lucide-react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { Badge } from "@/components/ui/badge"
import { useAgentDefinitions } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentDefinition } from "@/types/agents"

interface AgentCommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateNew: () => void
}

export function AgentCommandPalette({
  open,
  onOpenChange,
  onCreateNew,
}: AgentCommandPaletteProps) {
  const { data } = useAgentDefinitions()
  const { selectAgent, setActiveTab, recentAgentIds, addRecentAgent } =
    useAgentStore()

  const agents = data?.items ?? []
  const activeAgents = agents.filter((a) => a.status === "active")
  const recentAgents = recentAgentIds
    .map((id) => agents.find((a) => a.id === id))
    .filter(Boolean) as AgentDefinition[]

  const handleSelect = (agent: AgentDefinition, tab: "chat" | "overview" | "config") => {
    selectAgent(agent.id)
    setActiveTab(tab)
    addRecentAgent(agent.id)
    onOpenChange(false)
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search agents or type a command..." />
      <CommandList className="max-h-[400px]">
        <CommandEmpty>
          <div className="flex flex-col items-center py-6">
            <Bot className="h-10 w-10 text-muted-foreground/40 mb-2" />
            <p className="text-sm text-muted-foreground">No agents found</p>
            <button
              className="text-sm text-primary hover:underline mt-1"
              onClick={() => {
                onOpenChange(false)
                onCreateNew()
              }}
            >
              Create your first agent
            </button>
          </div>
        </CommandEmpty>

        {/* Quick Actions */}
        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() => {
              onOpenChange(false)
              onCreateNew()
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Create New Agent
          </CommandItem>
        </CommandGroup>

        {/* Recent Agents */}
        {recentAgents.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Recent">
              {recentAgents.slice(0, 5).map((agent) => (
                <AgentCommandItem
                  key={`recent-${agent.id}`}
                  agent={agent}
                  onChat={() => handleSelect(agent, "chat")}
                  onConfigure={() => handleSelect(agent, "config")}
                  onView={() => handleSelect(agent, "overview")}
                />
              ))}
            </CommandGroup>
          </>
        )}

        {/* Active Agents */}
        {activeAgents.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Active Agents">
              {activeAgents.map((agent) => (
                <AgentCommandItem
                  key={agent.id}
                  agent={agent}
                  onChat={() => handleSelect(agent, "chat")}
                  onConfigure={() => handleSelect(agent, "config")}
                  onView={() => handleSelect(agent, "overview")}
                />
              ))}
            </CommandGroup>
          </>
        )}

        {/* All Agents (if different from active) */}
        {agents.length > activeAgents.length && (
          <>
            <CommandSeparator />
            <CommandGroup heading="All Agents">
              {agents
                .filter((a) => a.status !== "active")
                .map((agent) => (
                  <AgentCommandItem
                    key={`all-${agent.id}`}
                    agent={agent}
                    onChat={() => handleSelect(agent, "chat")}
                    onConfigure={() => handleSelect(agent, "config")}
                    onView={() => handleSelect(agent, "overview")}
                  />
                ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  )
}

function AgentCommandItem({
  agent,
  onChat,
}: {
  agent: AgentDefinition
  onChat: () => void
  onConfigure: () => void
  onView: () => void
}) {
  return (
    <CommandItem
      value={`${agent.name} ${agent.slug} ${agent.description}`}
      onSelect={onChat}
    >
      <div className="flex items-center gap-3 w-full">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            agent.status === "active"
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground",
          )}
        >
          <Bot className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium truncate">{agent.name}</span>
            <Badge
              variant={agent.status === "active" ? "default" : "secondary"}
              className="text-[9px] h-4 px-1"
            >
              {agent.status}
            </Badge>
          </div>
          {agent.description && (
            <span className="text-xs text-muted-foreground line-clamp-1">
              {agent.description}
            </span>
          )}
        </div>
        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      </div>
    </CommandItem>
  )
}
