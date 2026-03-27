import { useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Plus, Clock, Check, AlertCircle } from "lucide-react"
import {
  useConfiguratorSessions,
  useConfigurationTemplates,
} from "@/apps/cpq/hooks/use-configurator"
import type {
  ConfigurationSession,
  ConfigurationTemplate,
  SessionStatus,
} from "@/apps/cpq/types/configurator"
import { cn } from "@/lib/utils"

interface SessionManagerProps {
  productId: string
  onSessionSelect: (sessionId: string) => void
  currentSessionId: string | null
}

// ── Status badge variant mapping ─────────────────────────

const statusConfig: Record<
  SessionStatus,
  {
    variant: "default" | "secondary" | "outline" | "destructive"
    icon: typeof Clock
    label: string
  }
> = {
  in_progress: { variant: "secondary", icon: Clock, label: "In Progress" },
  complete: { variant: "default", icon: Check, label: "Complete" },
  invalid: { variant: "destructive", icon: AlertCircle, label: "Invalid" },
  locked: { variant: "outline", icon: Clock, label: "Locked" },
}

// ── Date formatter ───────────────────────────────────────

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return "Just now"
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return formatDate(dateStr)
}

// ── Session card ─────────────────────────────────────────

function SessionCard({
  session,
  isCurrent,
  onSelect,
}: {
  session: ConfigurationSession
  isCurrent: boolean
  onSelect: () => void
}) {
  const config = statusConfig[session.status] ?? statusConfig.in_progress
  const StatusIcon = config.icon
  const selectionCount = session.selections?.length ?? 0

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left rounded-lg border p-3 transition-colors hover:bg-muted/50",
        isCurrent && "border-primary bg-primary/5 ring-1 ring-primary/20",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">
            {session.name ?? `Session ${session.id.slice(0, 8)}`}
          </p>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">
            {session.id.slice(0, 8)}...
          </p>
        </div>
        <Badge variant={config.variant} className="shrink-0 text-[10px] gap-1">
          <StatusIcon className="h-3 w-3" />
          {config.label}
        </Badge>
      </div>
      <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
        <span>{selectionCount} selection{selectionCount !== 1 ? "s" : ""}</span>
        <span>{formatRelativeTime(session.updated_at)}</span>
      </div>
    </button>
  )
}

// ── Template card ─────────────────────────────────────────

function TemplateCard({
  template,
  onStart,
}: {
  template: ConfigurationTemplate
  onStart: () => void
}) {
  const selectionCount = template.selections?.length ?? 0

  return (
    <div className="flex items-center justify-between rounded-lg border p-3 gap-2">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{template.name}</p>
        <div className="flex items-center gap-2 mt-1">
          {template.is_partial && (
            <Badge variant="outline" className="text-[10px]">
              Partial
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {selectionCount} preset{selectionCount !== 1 ? "s" : ""}
          </span>
        </div>
      </div>
      <Button variant="outline" size="sm" onClick={onStart} className="shrink-0">
        Start
      </Button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────

export function SessionManager({
  productId,
  onSessionSelect,
  currentSessionId,
}: SessionManagerProps) {
  const { data: sessionsData, isLoading: sessionsLoading } =
    useConfiguratorSessions({ product_id: productId })

  const { data: templatesData, isLoading: templatesLoading } =
    useConfigurationTemplates(productId)

  const sessions = useMemo(() => {
    const items = sessionsData?.items ?? []
    // Sort by updated_at descending (most recent first)
    return [...items].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
  }, [sessionsData])

  const templates = useMemo(() => templatesData?.items ?? [], [templatesData])

  const handleNewSession = () => {
    // This triggers the parent to create a new session
    // by passing an empty string which the parent interprets as "create new"
    onSessionSelect("")
  }

  const handleStartFromTemplate = (templateId: string) => {
    // Pass the template ID prefixed to indicate template start
    onSessionSelect(`template:${templateId}`)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Sessions</CardTitle>
        <Button size="sm" onClick={handleNewSession}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          New Session
        </Button>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Existing sessions */}
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Existing Sessions
          </h4>

          {sessionsLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-20 rounded-lg border bg-muted/30 animate-pulse"
                />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No existing sessions for this product.
            </p>
          ) : (
            <ScrollArea className="max-h-[280px]">
              <div className="space-y-2 pr-2">
                {sessions.map((session) => (
                  <SessionCard
                    key={session.id}
                    session={session}
                    isCurrent={session.id === currentSessionId}
                    onSelect={() => onSessionSelect(session.id)}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </div>

        {/* Templates */}
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Templates
          </h4>

          {templatesLoading ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div
                  key={i}
                  className="h-16 rounded-lg border bg-muted/30 animate-pulse"
                />
              ))}
            </div>
          ) : templates.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No templates available. Save a configuration as a template to start using them.
            </p>
          ) : (
            <ScrollArea className="max-h-[200px]">
              <div className="space-y-2 pr-2">
                {templates.map((template) => (
                  <TemplateCard
                    key={template.id}
                    template={template}
                    onStart={() => handleStartFromTemplate(template.id)}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
