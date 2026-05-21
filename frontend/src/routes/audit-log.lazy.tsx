import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Shield, ChevronDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { AuthGuard } from "@/components/auth/auth-guard"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { useAuditLogs } from "@/hooks/use-audit-logs"
import { formatRelativeTime, formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { AuditLog } from "@/types/api"

export const Route = createLazyFileRoute("/audit-log")({
  component: AuditLogPage,
})

const actionColors: Record<string, string> = {
  create: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  read: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  update: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  delete: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  login: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  logout: "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400",
}

function AuditEntry({ entry }: { entry: AuditLog }) {
  const { t } = useTranslation("audit_log")
  const colorClass = actionColors[entry.action] ?? actionColors.read

  return (
    <div className="flex gap-4 pb-6 last:pb-0 relative">
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div className={cn("w-3 h-3 rounded-full shrink-0 mt-1", colorClass.split(" ")[0])} />
        <div className="w-px flex-1 bg-border mt-1" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className={cn("border-transparent text-xs", colorClass)}>
            {entry.action}
          </Badge>
          <span className="text-sm font-medium">
            {entry.resource_type}
            {entry.resource_id && (
              <span className="text-muted-foreground font-mono text-xs ml-1">
                {entry.resource_id.slice(0, 8)}
              </span>
            )}
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {entry.actor_id && <span>{entry.actor_id}</span>}
          {entry.actor_id && <span>&middot;</span>}
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="cursor-default">{formatRelativeTime(entry.occurred_at)}</span>
              </TooltipTrigger>
              <TooltipContent>{formatDateTime(entry.occurred_at)}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {entry.ip_address && (
            <>
              <span>&middot;</span>
              <span>{entry.ip_address}</span>
            </>
          )}
        </div>

        {entry.changes && Object.keys(entry.changes).length > 0 && (
          <Collapsible>
            <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <ChevronDown className="h-3 w-3" />
              {t("metadata")}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="mt-2 rounded-md bg-muted p-3 text-xs overflow-x-auto">
                {JSON.stringify(entry.changes, null, 2)}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  )
}

function useActionOptions() {
  const { t } = useTranslation("audit_log")
  return [
    { value: "all", label: t("actions.all") },
    { value: "create", label: t("actions.create") },
    { value: "read", label: t("actions.read") },
    { value: "update", label: t("actions.update") },
    { value: "delete", label: t("actions.delete") },
    { value: "login", label: t("actions.login") },
    { value: "logout", label: t("actions.logout") },
  ]
}

function useResourceOptions() {
  const { t } = useTranslation("audit_log")
  return [
    { value: "all", label: t("resources.all") },
    { value: "user", label: t("resources.user") },
    { value: "tenant", label: t("resources.tenant") },
    { value: "api_key", label: t("resources.api_key") },
    { value: "job", label: t("resources.job") },
    { value: "file", label: t("resources.file") },
    { value: "webhook", label: t("resources.webhook") },
    { value: "subscription", label: t("resources.subscription") },
  ]
}

function AuditLogPage() {
  return (
    <AuthGuard requiredRole="admin">
      <AuditLogPageContent />
    </AuthGuard>
  )
}

function AuditLogPageContent() {
  const { t } = useTranslation("audit_log")
  const [actionFilter, setActionFilter] = useState("all")
  const [resourceFilter, setResourceFilter] = useState("all")
  const actionOptions = useActionOptions()
  const resourceOptions = useResourceOptions()

  const { data, isLoading, error, refetch } = useAuditLogs({
    action: actionFilter === "all" ? undefined : actionFilter,
    resource_type: resourceFilter === "all" ? undefined : resourceFilter,
  })

  return (
    <div className="space-y-6">
        <PageHeader title={t("title")} description={t("description")} />

        {/* Filters */}
        <div className="flex items-center gap-3">
          <Select value={actionFilter} onValueChange={setActionFilter}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder={t("action_filter")} />
            </SelectTrigger>
            <SelectContent>
              {actionOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={resourceFilter} onValueChange={setResourceFilter}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder={t("resource_filter")} />
            </SelectTrigger>
            <SelectContent>
              {resourceOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Timeline */}
        <Card>
          <CardContent className="p-6">
            {isLoading ? (
              <LoadingState variant="skeleton" rows={5} />
            ) : error ? (
              <ErrorState
                message={error instanceof Error ? error.message : t("load_failed")}
                onRetry={() => refetch()}
              />
            ) : !data || data.length === 0 ? (
              <EmptyState
                icon={Shield}
                title={t("no_entries")}
                description={t("no_entries_desc")}
              />
            ) : (
              <div className="space-y-0">
                {data.map((entry) => (
                  <AuditEntry key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
  )
}
