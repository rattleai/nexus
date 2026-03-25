import { createLazyFileRoute } from "@tanstack/react-router"
import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Bot, Plus, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { EmptyState } from "@/components/empty-state"
import { useAgentDefinitions } from "@/hooks/use-agents"
import type { AgentDefinition } from "@/types/agents"

export const Route = createLazyFileRoute("/settings/agents")({
  component: SettingsAgentsPage,
})

function AgentCard({ agent }: { agent: AgentDefinition }) {
  return (
    <Card className="group relative overflow-hidden border transition-colors hover:border-primary/50">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base">{agent.name}</CardTitle>
              <CardDescription className="text-xs">{agent.model}</CardDescription>
            </div>
          </div>
          <Badge variant={agent.status === "active" ? "default" : "secondary"}>
            {agent.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground line-clamp-2">{agent.description}</p>
      </CardContent>
    </Card>
  )
}

function SettingsAgentsPage() {
  const { data, isLoading } = useAgentDefinitions()
  const agents = data?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Definitions"
        description="Configure and manage your AI agent definitions. Create agents in the workspace and manage their configurations here."
        actions={
          <Button asChild>
            <Link to="/agents/workspace">
              <ExternalLink className="mr-2 h-4 w-4" />
              Open Workspace
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <LoadingState variant="skeleton" rows={3} />
      ) : agents.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No agents yet"
          description="Create your first agent in the Agent Workspace to get started."
          action={
            <Button asChild>
              <Link to="/agents/workspace">
                <Plus className="mr-2 h-4 w-4" />
                Create Agent
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  )
}
