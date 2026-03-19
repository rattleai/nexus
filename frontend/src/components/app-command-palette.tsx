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

/**
 * Unified Ctrl+K command palette.
 *
 * Default mode  — navigation + quick actions
 * Agent mode    — type ">" to browse/search agents, select to chat
 */
export function AppCommandPalette() {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")
  const navigate = useNavigate()
  const router = useRouterState()
  const currentPath = router.location.pathname

  // Agent data — only fetched when palette is open
  const { data: agentData } = useAgentDefinitions()
  const { selectAgent, setActiveTab, recentAgentIds, addRecentAgent } =
    useAgentStore()

  const isAgentMode = search.startsWith(">")
  const agentSearch = isAgentMode ? search.slice(1).trim().toLowerCase() : ""

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

  // Reset search when closing
  React.useEffect(() => {
    if (!open) setSearch("")
  }, [open])

  const close = () => setOpen(false)

  const go = (path: string) => {
    navigate({ to: path })
    close()
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

  const handleAgentSelect = (
    agent: AgentDefinition,
    tab: "chat" | "overview" | "config" = "chat",
  ) => {
    // Navigate to /agents if not already there
    if (!currentPath.startsWith("/agents")) {
      navigate({ to: "/agents" })
    }
    selectAgent(agent.id)
    setActiveTab(tab)
    addRecentAgent(agent.id)
    close()
  }

  // ── Render ───────────────────────────────────────────────────────
  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        placeholder={
          isAgentMode
            ? "Search agents by name..."
            : "Type a command or search... Type > for agents"
        }
        value={search}
        onValueChange={setSearch}
      />
      <CommandList className="max-h-[420px]">
        {isAgentMode ? (
          /* ── Agent Mode ───────────────────────────────── */
          <>
            <CommandEmpty>
              <div className="flex flex-col items-center py-6 gap-2">
                <Bot className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  {agentSearch ? "No matching agents" : "No agents yet"}
                </p>
                <button
                  className="text-sm text-primary hover:underline"
                  onClick={() => {
                    go("/agents")
                    // Will trigger create dialog via store
                  }}
                >
                  Create your first agent
                </button>
              </div>
            </CommandEmpty>

            {/* Create new */}
            <CommandGroup heading="Actions">
              <CommandItem
                onSelect={() => go("/agents")}
                value="> create new agent"
              >
                <Plus className="mr-2 h-4 w-4" />
                Create New Agent
              </CommandItem>
            </CommandGroup>

            {filteredAgents ? (
              /* Search results */
              filteredAgents.length > 0 && (
                <>
                  <CommandSeparator />
                  <CommandGroup heading="Results">
                    {filteredAgents.map((agent) => (
                      <AgentItem
                        key={agent.id}
                        agent={agent}
                        onSelect={(tab) => handleAgentSelect(agent, tab)}
                      />
                    ))}
                  </CommandGroup>
                </>
              )
            ) : (
              /* Browsing (no search text after >) */
              <>
                {recentAgents.length > 0 && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Recent">
                      {recentAgents.slice(0, 5).map((agent) => (
                        <AgentItem
                          key={`r-${agent.id}`}
                          agent={agent}
                          onSelect={(tab) => handleAgentSelect(agent, tab)}
                        />
                      ))}
                    </CommandGroup>
                  </>
                )}
                {activeAgents.length > 0 && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Active Agents">
                      {activeAgents.map((agent) => (
                        <AgentItem
                          key={agent.id}
                          agent={agent}
                          onSelect={(tab) => handleAgentSelect(agent, tab)}
                        />
                      ))}
                    </CommandGroup>
                  </>
                )}
                {agents.length > activeAgents.length && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="All Agents">
                      {agents
                        .filter((a) => a.status !== "active")
                        .map((agent) => (
                          <AgentItem
                            key={`a-${agent.id}`}
                            agent={agent}
                            onSelect={(tab) => handleAgentSelect(agent, tab)}
                          />
                        ))}
                    </CommandGroup>
                  </>
                )}
              </>
            )}
          </>
        ) : (
          /* ── Default Mode ─────────────────────────────── */
          <>
            <CommandEmpty>No results found.</CommandEmpty>

            {/* Agent entry point */}
            <CommandGroup heading="Agents">
              <CommandItem
                onSelect={() => setSearch(">")}
                value="agents browse search >"
              >
                <Bot className="mr-2 h-4 w-4" />
                <span className="flex-1">Search Agents</span>
                <kbd className="ml-auto text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
                  &gt;
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
                  onSelect={() => setSearch(">")}
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
  onSelect: (tab: "chat" | "overview" | "config") => void
}) {
  return (
    <CommandItem
      value={`> ${agent.name} ${agent.slug} ${agent.description}`}
      onSelect={() => onSelect("chat")}
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
