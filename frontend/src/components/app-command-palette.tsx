import * as React from "react"
import { useNavigate, useRouterState } from "@tanstack/react-router"
import {
  LayoutDashboard,
  Bot,
  MessageSquare,
  Briefcase,
  FolderOpen,
  Key,
  CreditCard,
  Users,
  Webhook,
  Shield,
  Settings,
  Plus,
  ChevronRight,
  X,
  ArrowRight,
} from "lucide-react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import { Badge } from "@/components/ui/badge"
import { useAgentDefinitions } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentDefinition } from "@/types/agents"

type PaletteMode = "default" | "agent-browse" | "agent-task"

/**
 * Unified Ctrl+K command palette.
 *
 * Default mode     — navigation + quick actions
 * Agent browse (@) — type "@" to browse/search agents
 * Agent task       — agent locked in, type task + Enter to send
 */
export function AppCommandPalette() {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")
  const [mode, setMode] = React.useState<PaletteMode>("default")
  const [selectedAgent, setSelectedAgent] =
    React.useState<AgentDefinition | null>(null)
  const [taskInput, setTaskInput] = React.useState("")
  const taskInputRef = React.useRef<HTMLInputElement>(null)

  const navigate = useNavigate()
  const router = useRouterState()
  const currentPath = router.location.pathname

  // Agent data
  const { data: agentData } = useAgentDefinitions()
  const {
    selectAgent,
    setActiveTab,
    recentAgentIds,
    addRecentAgent,
    setPendingMessage,
  } = useAgentStore()

  // Derive agent search text from input (everything after "@")
  const agentSearch =
    mode === "agent-browse" ? search.slice(1).trim().toLowerCase() : ""

  // Ctrl+K global binding
  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])

  // Reset state when closing
  React.useEffect(() => {
    if (!open) {
      setSearch("")
      setMode("default")
      setSelectedAgent(null)
      setTaskInput("")
    }
  }, [open])

  // Auto-focus task input when entering agent-task mode
  React.useEffect(() => {
    if (mode === "agent-task") {
      requestAnimationFrame(() => taskInputRef.current?.focus())
    }
  }, [mode])

  const close = () => setOpen(false)

  const go = (path: string) => {
    navigate({ to: path })
    close()
  }

  // Detect "@" trigger in search input
  const handleSearchChange = (value: string) => {
    setSearch(value)
    if (value.startsWith("@") && mode !== "agent-browse") {
      setMode("agent-browse")
    } else if (!value.startsWith("@") && mode === "agent-browse") {
      setMode("default")
    }
  }

  // ── Agent helpers ────────────────────────────────────────────────
  const agents = agentData?.items ?? []
  const activeAgents = agents.filter((a) => a.status === "active")
  const recentAgents = recentAgentIds
    .map((id) => agents.find((a) => a.id === id))
    .filter(Boolean) as AgentDefinition[]

  const filteredAgents = agentSearch
    ? agents.filter(
        (a) =>
          a.name.toLowerCase().includes(agentSearch) ||
          a.slug.toLowerCase().includes(agentSearch) ||
          a.description.toLowerCase().includes(agentSearch),
      )
    : null // null = show grouped (recent + active + all)

  // Select agent and move to task input mode
  const handleAgentPick = (agent: AgentDefinition) => {
    setSelectedAgent(agent)
    setMode("agent-task")
    setSearch("")
    setTaskInput("")
  }

  // Navigate to agent and optionally send a task
  const handleAgentSelect = (
    agent: AgentDefinition,
    tab: "chat" | "overview" | "config" = "chat",
    message?: string,
  ) => {
    if (message) {
      setPendingMessage(message)
    }
    if (!currentPath.startsWith("/agents")) {
      navigate({ to: "/agents" })
    }
    selectAgent(agent.id)
    setActiveTab(tab)
    addRecentAgent(agent.id)
    close()
  }

  // Submit the task for the locked-in agent
  const handleTaskSubmit = () => {
    const trimmed = taskInput.trim()
    if (!trimmed || !selectedAgent) return
    handleAgentSelect(selectedAgent, "chat", trimmed)
  }

  // Handle keyboard in agent-task mode
  const handleTaskKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleTaskSubmit()
    } else if (e.key === "Backspace" && taskInput === "") {
      // Go back to browse mode
      setMode("agent-browse")
      setSelectedAgent(null)
      setSearch("@")
    } else if (e.key === "Escape") {
      close()
    }
  }

  // Clear locked agent and return to browse
  const handleClearAgent = () => {
    setMode("agent-browse")
    setSelectedAgent(null)
    setSearch("@")
  }

  // ── Render ───────────────────────────────────────────────────────
  return (
    <CommandDialog open={open} onOpenChange={setOpen} shouldFilter={mode === "default"}>
      {mode === "agent-task" && selectedAgent ? (
        /* ── Agent Task Input (custom, replaces CommandInput) ── */
        <div className="flex items-center border-b px-3 gap-2">
          <Bot className="h-4 w-4 shrink-0 opacity-50" />
          <Badge
            variant="secondary"
            className="shrink-0 gap-1 cursor-pointer hover:bg-secondary/80 pr-1"
            onClick={handleClearAgent}
          >
            <span className="text-xs">@{selectedAgent.name}</span>
            <X className="h-3 w-3" />
          </Badge>
          <input
            ref={taskInputRef}
            value={taskInput}
            onChange={(e) => setTaskInput(e.target.value)}
            onKeyDown={handleTaskKeyDown}
            placeholder={`Type a task for ${selectedAgent.name}...`}
            className="flex h-11 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
          />
          {taskInput.trim() && (
            <button
              onClick={handleTaskSubmit}
              className="shrink-0 flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-medium"
            >
              Send
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ) : (
        <CommandInput
          placeholder={
            mode === "agent-browse"
              ? "Search agents by name..."
              : "Type a command or search... Type @ for agents"
          }
          value={search}
          onValueChange={handleSearchChange}
        />
      )}
      <CommandList className="max-h-[420px]">
        {mode === "agent-task" ? (
          /* ── Task mode hint ─────────────────────────── */
          <div className="py-6 px-4 text-center">
            <div className="flex items-center justify-center gap-2 mb-3">
              <div
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-lg",
                  selectedAgent?.status === "active"
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground",
                )}
              >
                <Bot className="h-5 w-5" />
              </div>
              <div className="text-left">
                <p className="text-sm font-medium">{selectedAgent?.name}</p>
                {selectedAgent?.description && (
                  <p className="text-xs text-muted-foreground line-clamp-1">
                    {selectedAgent.description}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center justify-center gap-4 text-[11px] text-muted-foreground">
              <span>
                <kbd className="bg-muted px-1.5 py-0.5 rounded font-mono text-[10px]">
                  Enter
                </kbd>{" "}
                to send
              </span>
              <span>
                <kbd className="bg-muted px-1.5 py-0.5 rounded font-mono text-[10px]">
                  Backspace
                </kbd>{" "}
                to change agent
              </span>
              <span>
                <kbd className="bg-muted px-1.5 py-0.5 rounded font-mono text-[10px]">
                  Esc
                </kbd>{" "}
                to close
              </span>
            </div>
          </div>
        ) : mode === "agent-browse" ? (
          /* ── Agent Browse Mode ──────────────────────── */
          <>
            <CommandEmpty>
              <div className="flex flex-col items-center py-6 gap-2">
                <Bot className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  {agentSearch ? "No matching agents" : "No agents yet"}
                </p>
                <button
                  className="text-sm text-primary hover:underline"
                  onClick={() => go("/agents")}
                >
                  Create your first agent
                </button>
              </div>
            </CommandEmpty>

            {filteredAgents ? (
              /* Search results */
              filteredAgents.length > 0 && (
                <CommandGroup heading="Results">
                  {filteredAgents.map((agent) => (
                    <AgentItem
                      key={agent.id}
                      agent={agent}
                      onSelect={() => handleAgentPick(agent)}
                    />
                  ))}
                </CommandGroup>
              )
            ) : (
              /* Browsing (no search text after @) */
              <>
                {recentAgents.length > 0 && (
                  <CommandGroup heading="Recent">
                    {recentAgents.slice(0, 5).map((agent) => (
                      <AgentItem
                        key={`r-${agent.id}`}
                        agent={agent}
                        onSelect={() => handleAgentPick(agent)}
                      />
                    ))}
                  </CommandGroup>
                )}
                {activeAgents.length > 0 && (
                  <CommandGroup heading="Active Agents">
                    {activeAgents.map((agent) => (
                      <AgentItem
                        key={agent.id}
                        agent={agent}
                        onSelect={() => handleAgentPick(agent)}
                      />
                    ))}
                  </CommandGroup>
                )}
                {agents.length > activeAgents.length && (
                  <CommandGroup heading="All Agents">
                    {agents
                      .filter((a) => a.status !== "active")
                      .map((agent) => (
                        <AgentItem
                          key={`a-${agent.id}`}
                          agent={agent}
                          onSelect={() => handleAgentPick(agent)}
                        />
                      ))}
                  </CommandGroup>
                )}
              </>
            )}

            {/* Create new — at the bottom for discoverability */}
            <CommandSeparator />
            <CommandGroup heading="Actions">
              <CommandItem
                onSelect={() => go("/agents")}
                value="@ create new agent"
              >
                <Plus className="mr-2 h-4 w-4" />
                Create New Agent
              </CommandItem>
            </CommandGroup>
          </>
        ) : (
          /* ── Default Mode ─────────────────────────────── */
          <>
            <CommandEmpty>No results found.</CommandEmpty>

            {/* Agent entry point */}
            <CommandGroup heading="Agents">
              <CommandItem
                onSelect={() => {
                  setSearch("@")
                  setMode("agent-browse")
                }}
                value="agents browse search @"
              >
                <Bot className="mr-2 h-4 w-4" />
                <span className="flex-1">Search Agents</span>
                <kbd className="ml-auto text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
                  @
                </kbd>
              </CommandItem>
              {activeAgents.slice(0, 3).map((agent) => (
                <CommandItem
                  key={agent.id}
                  onSelect={() => handleAgentSelect(agent, "chat")}
                  value={`agent ${agent.name} ${agent.slug} chat`}
                >
                  <div className="mr-2 flex h-5 w-5 items-center justify-center rounded bg-primary/10">
                    <Bot className="h-3 w-3 text-primary" />
                  </div>
                  <span className="flex-1 truncate">{agent.name}</span>
                  <MessageSquare className="h-3 w-3 text-muted-foreground" />
                </CommandItem>
              ))}
              {agents.length > 3 && (
                <CommandItem
                  onSelect={() => {
                    setSearch("@")
                    setMode("agent-browse")
                  }}
                  value="view all agents"
                >
                  <ChevronRight className="mr-2 h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">
                    View all {agents.length} agents...
                  </span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />

            {/* Navigation */}
            <CommandGroup heading="Navigation">
              <CommandItem onSelect={() => go("/")} value="dashboard home">
                <LayoutDashboard className="mr-2 h-4 w-4" />
                Dashboard
              </CommandItem>
              <CommandItem onSelect={() => go("/agents")} value="agents workspace">
                <Bot className="mr-2 h-4 w-4" />
                Agent Workspace
              </CommandItem>
              <CommandItem onSelect={() => go("/chat")} value="ai chat">
                <MessageSquare className="mr-2 h-4 w-4" />
                AI Chat
              </CommandItem>
              <CommandItem onSelect={() => go("/jobs")} value="jobs tasks">
                <Briefcase className="mr-2 h-4 w-4" />
                Jobs
              </CommandItem>
              <CommandItem onSelect={() => go("/files")} value="files documents">
                <FolderOpen className="mr-2 h-4 w-4" />
                Files
              </CommandItem>
              <CommandItem onSelect={() => go("/api-keys")} value="api keys">
                <Key className="mr-2 h-4 w-4" />
                API Keys
              </CommandItem>
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading="Organization">
              <CommandItem onSelect={() => go("/billing")} value="billing payment">
                <CreditCard className="mr-2 h-4 w-4" />
                Billing
              </CommandItem>
              <CommandItem onSelect={() => go("/team")} value="team members">
                <Users className="mr-2 h-4 w-4" />
                Team
              </CommandItem>
              <CommandItem onSelect={() => go("/webhooks")} value="webhooks">
                <Webhook className="mr-2 h-4 w-4" />
                Webhooks
              </CommandItem>
              <CommandItem onSelect={() => go("/audit-log")} value="audit log">
                <Shield className="mr-2 h-4 w-4" />
                Audit Log
              </CommandItem>
              <CommandItem onSelect={() => go("/settings")} value="settings preferences">
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </CommandItem>
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  )
}

// ── Agent list item ────────────────────────────────────────────────

function AgentItem({
  agent,
  onSelect,
}: {
  agent: AgentDefinition
  onSelect: () => void
}) {
  return (
    <CommandItem
      value={`${agent.name} ${agent.slug} ${agent.description}`}
      onSelect={onSelect}
    >
      <div className="flex items-center gap-3 w-full">
        <div
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
            agent.status === "active"
              ? "bg-primary/10 text-primary"
              : agent.status === "draft"
                ? "bg-muted text-muted-foreground"
                : "bg-destructive/10 text-destructive",
          )}
        >
          <Bot className="h-3.5 w-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium truncate">{agent.name}</span>
            <Badge
              variant={agent.status === "active" ? "default" : "secondary"}
              className="text-[9px] h-4 px-1 shrink-0"
            >
              {agent.status}
            </Badge>
          </div>
          {agent.description && (
            <p className="text-xs text-muted-foreground line-clamp-1">
              {agent.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0 text-muted-foreground">
          <span className="text-[10px]">{agent.model}</span>
          <MessageSquare className="h-3.5 w-3.5" />
        </div>
      </div>
    </CommandItem>
  )
}
