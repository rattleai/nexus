import * as React from "react"
import {
  AlertTriangle,
  Bot,
  Plus,
  Search,
  LayoutGrid,
  MessageSquare,
  Settings,
  Shield,
  Activity,
  Loader2,
  Sparkles,
  Command,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { AgentCard } from "./agent-card"
import { AgentOverview } from "./agent-overview"
import { AgentChatPanel } from "./agent-chat-panel"
import { AgentConfigPanel } from "./agent-config-panel"
import { GovernancePanel } from "./governance-panel"
import { AgentRunsPanel } from "./agent-runs-panel"
import { CreateAgentDialog } from "./create-agent-dialog"
import {
  useAgentDefinitions,
  useAgentDefinition,
  useDeleteAgent,
} from "@/hooks/use-agents"
import { useAgentStore, type AgentTab } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import { StatusDot, statusToVariant } from "@/components/status-dot"
import { useIsMobile } from "@/hooks/use-mobile"
import { ErrorBoundary } from "@/components/error-boundary"

const TABS: { id: AgentTab; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "config", label: "Config", icon: Settings },
  { id: "governance", label: "Governance", icon: Shield },
  { id: "runs", label: "Runs", icon: Activity },
]

const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform)
const modKey = isMac ? "\u2318" : "Ctrl"

export function AgentWorkspace() {
  const isMobile = useIsMobile()
  const {
    selectedAgentId,
    activeTab,
    searchQuery,
    statusFilter,
    selectAgent,
    setActiveTab,
    setSearchQuery,
    setStatusFilter,
    addRecentAgent,
  } = useAgentStore()

  const [createOpen, setCreateOpen] = React.useState(false)
  const [deleteId, setDeleteId] = React.useState<string | null>(null)
  const [isDeleting, setIsDeleting] = React.useState(false)

  const { data, isLoading } = useAgentDefinitions(
    statusFilter !== "all" ? statusFilter : undefined,
  )
  const { data: selectedAgent } = useAgentDefinition(selectedAgentId)
  const deleteAgent = useDeleteAgent()

  const agents = React.useMemo(() => {
    const items = data?.items ?? []
    if (!searchQuery) return items
    const q = searchQuery.toLowerCase()
    return items.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.slug.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q),
    )
  }, [data, searchQuery])

  const handleSelectAgent = (id: string) => {
    selectAgent(id)
    addRecentAgent(id)
  }

  const handleDelete = async () => {
    if (!deleteId || isDeleting) return
    setIsDeleting(true)
    try {
      await deleteAgent.mutateAsync(deleteId)
      if (selectedAgentId === deleteId) selectAgent(null)
    } finally {
      setIsDeleting(false)
      setDeleteId(null)
    }
  }

  const handleAgentCreated = (agentId: string) => {
    selectAgent(agentId)
    addRecentAgent(agentId)
    setActiveTab("config")
  }

  // Sidebar content
  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Agents
          </h2>
          <div className="flex items-center gap-1">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label="Open command palette"
                    onClick={() => {
                      // Programmatically dispatch Ctrl+K to open the global palette
                      document.dispatchEvent(
                        new KeyboardEvent("keydown", { key: "k", metaKey: true }),
                      )
                    }}
                  >
                    <Command className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  <p>
                    Quick switch <kbd className="ml-1 text-[10px]">{modKey}+K &gt;</kbd>
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={() => setCreateOpen(true)}
            >
              <Plus className="mr-1 h-3 w-3" />
              New
            </Button>
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search agents..."
            className="h-8 pl-8 text-xs"
          />
        </div>

        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Separator />

      {/* Agent list */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : agents.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-center px-4">
              <Bot className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground mb-1">
                {searchQuery ? "No agents match your search" : "No agents yet"}
              </p>
              {!searchQuery && (
                <Button
                  variant="link"
                  size="sm"
                  className="text-xs"
                  onClick={() => setCreateOpen(true)}
                >
                  <Sparkles className="mr-1 h-3 w-3" />
                  Create your first agent
                </Button>
              )}
            </div>
          ) : (
            agents.map((agent) => (
              <div key={agent.id} className="group">
                <AgentCard
                  agent={agent}
                  isSelected={selectedAgentId === agent.id}
                  onSelect={() => handleSelectAgent(agent.id)}
                  onChat={() => {
                    handleSelectAgent(agent.id)
                    setActiveTab("chat")
                  }}
                  onConfigure={() => {
                    handleSelectAgent(agent.id)
                    setActiveTab("config")
                  }}
                  onDelete={() => setDeleteId(agent.id)}
                />
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="p-3 border-t">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{data?.total ?? 0} agents</span>
          <kbd className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono">
            {modKey}+K &gt;
          </kbd>
        </div>
      </div>
    </div>
  )

  // Main panel content
  const mainContent = selectedAgent ? (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Tab bar */}
      <div className="flex items-center border-b px-4 py-2 gap-4">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
              selectedAgent.status === "active"
                ? "bg-primary/10 text-primary"
                : "bg-muted text-muted-foreground",
            )}
          >
            <Bot className="h-3.5 w-3.5" />
          </div>
          <span className="font-medium text-sm truncate">
            {selectedAgent.name}
          </span>
          <StatusDot variant={statusToVariant(selectedAgent.status)} />
        </div>

        <Separator orientation="vertical" className="h-5" />

        <Tabs
          value={activeTab}
          onValueChange={(v) => setActiveTab(v as AgentTab)}
          className="flex-1"
        >
          <TabsList className="h-8 bg-transparent p-0 gap-0">
            {TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <TabsTrigger
                  key={tab.id}
                  value={tab.id}
                  className="h-8 px-3 text-xs data-[state=active]:bg-accent data-[state=active]:shadow-none rounded-md"
                >
                  <Icon className="mr-1.5 h-3.5 w-3.5" />
                  {tab.label}
                </TabsTrigger>
              )
            })}
          </TabsList>
        </Tabs>
      </div>

      {/* Tab content — chat gets its own full-height container, other tabs use ScrollArea */}
      {activeTab === "chat" ? (
        <div className="flex-1 p-6 min-h-0">
          <ErrorBoundary fallback={<PanelErrorFallback tab="chat" />}>
            <AgentChatPanel agent={selectedAgent} />
          </ErrorBoundary>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="p-6">
            {activeTab === "overview" && (
              <ErrorBoundary fallback={<PanelErrorFallback tab="overview" />}>
                <AgentOverview agent={selectedAgent} />
              </ErrorBoundary>
            )}
            {activeTab === "config" && (
              <ErrorBoundary fallback={<PanelErrorFallback tab="config" />}>
                <AgentConfigPanel agent={selectedAgent} />
              </ErrorBoundary>
            )}
            {activeTab === "governance" && (
              <ErrorBoundary fallback={<PanelErrorFallback tab="governance" />}>
                <GovernancePanel agent={selectedAgent} />
              </ErrorBoundary>
            )}
            {activeTab === "runs" && (
              <ErrorBoundary fallback={<PanelErrorFallback tab="runs" />}>
                <AgentRunsPanel agent={selectedAgent} />
              </ErrorBoundary>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  ) : (
    <EmptyState onCreateNew={() => setCreateOpen(true)} />
  )

  return (
    <>
      {isMobile ? (
        <div className="flex flex-col flex-1 min-h-0">
          {!selectedAgentId ? (
            sidebarContent
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="mx-4 mt-2 self-start h-7 text-xs"
                onClick={() => selectAgent(null)}
              >
                Back to list
              </Button>
              {mainContent}
            </>
          )}
        </div>
      ) : (
        <div className="flex flex-1 min-h-0 rounded-xl border overflow-hidden">
          <div className="w-72 shrink-0 border-r bg-background">
            {sidebarContent}
          </div>
          <div className="flex-1 min-w-0 bg-background">
            {mainContent}
          </div>
        </div>
      )}

      {/* Dialogs */}
      <CreateAgentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={handleAgentCreated}
      />

      <AlertDialog
        open={!!deleteId}
        onOpenChange={(open) => !open && setDeleteId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Agent</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently deactivate this agent. Running instances will
              not be affected. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isDeleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isDeleting ? "Deleting..." : "Delete Agent"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function PanelErrorFallback({ tab }: { tab: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-12 px-4">
      <AlertTriangle className="h-10 w-10 text-destructive mb-3" />
      <h3 className="text-sm font-semibold mb-1">
        Something went wrong in the {tab} panel
      </h3>
      <p className="text-xs text-muted-foreground mb-4">
        An unexpected error occurred. Try switching tabs or reloading the page.
      </p>
      <Button
        variant="outline"
        size="sm"
        onClick={() => window.location.reload()}
      >
        Reload page
      </Button>
    </div>
  )
}

function EmptyState({ onCreateNew }: { onCreateNew: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 text-center px-8">
      <div className="relative mb-6">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 shadow-inner">
          <Bot className="h-10 w-10 text-primary" />
        </div>
        <div className="absolute -top-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md">
          <Sparkles className="h-3.5 w-3.5" />
        </div>
      </div>
      <h3 className="text-xl font-semibold mb-2">Agent Workspace</h3>
      <p className="text-sm text-muted-foreground max-w-md mb-6">
        Select an agent from the sidebar to view its details, chat with it, or
        configure its behavior. Press{" "}
        <kbd className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">
          {modKey}+K
        </kbd>{" "}
        then type{" "}
        <kbd className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">
          &gt;
        </kbd>{" "}
        to quickly find and switch between agents.
      </p>
      <div className="flex gap-3">
        <Button onClick={onCreateNew}>
          <Plus className="mr-1.5 h-4 w-4" />
          Create Agent
        </Button>
        <Button
          variant="outline"
          onClick={() =>
            document.dispatchEvent(
              new KeyboardEvent("keydown", { key: "k", metaKey: true }),
            )
          }
        >
          <Command className="mr-1.5 h-4 w-4" />
          Search
          <kbd className="ml-1.5 text-[10px] bg-muted px-1 py-0.5 rounded font-mono">
            {modKey}+K
          </kbd>
        </Button>
      </div>
    </div>
  )
}
