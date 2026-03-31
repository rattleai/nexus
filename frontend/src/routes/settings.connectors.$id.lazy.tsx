import { createLazyFileRoute, Link, useParams } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { ArrowLeft, Plug, RefreshCw, Trash2, TestTube, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusDot } from "@/components/status-dot"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import {
  useConnection,
  useConnectionTools,
  useDeleteConnection,
  useTestConnection,
} from "@/hooks/use-connectors"
import { parseApiError } from "@/lib/api-client"
import { formatDate, formatDateTime } from "@/lib/format"

export const Route = createLazyFileRoute("/settings/connectors/$id")({
  component: ConnectionDetailPage,
})

const STATUS_MAP: Record<string, "active" | "inactive" | "error" | "draft"> = {
  active: "active",
  degraded: "draft",
  expired: "error",
  disconnected: "inactive",
  error: "error",
}

function ConnectionDetailPage() {
  const { id } = useParams({ from: "/settings/connectors/$id" })
  const { t } = useTranslation("connectors")
  const { t: tc } = useTranslation("common")
  const { data: connection, isLoading, error } = useConnection(id)
  const { data: tools } = useConnectionTools(id)
  const testConn = useTestConnection()
  const deleteConn = useDeleteConnection()

  if (isLoading) return <LoadingState variant="skeleton" rows={5} />
  if (error || !connection) return <ErrorState message="Connection not found" />

  const handleTest = async () => {
    try {
      const result = await testConn.mutateAsync(id)
      if (result.status === "ok") {
        toast.success(t("test_success", { ms: result.latency_ms }))
      } else {
        toast.error(result.message)
      }
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          to="/settings/connectors"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">{connection.display_name}</h1>
          <p className="text-sm text-muted-foreground">{connection.connector_name}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleTest} disabled={testConn.isPending}>
            <TestTube className="mr-2 h-4 w-4" />
            {t("test_connection")}
          </Button>
          <ConfirmDialog
            title={t("disconnect_title")}
            description={t("disconnect_desc", { name: connection.display_name })}
            variant="destructive"
            confirmLabel={tc("buttons.delete")}
            onConfirm={async () => {
              try {
                await deleteConn.mutateAsync(id)
                toast.success(t("disconnect_success"))
                window.location.href = "/settings/connectors"
              } catch (err) {
                const e = await parseApiError(err)
                toast.error(e.detail)
              }
            }}
          >
            <Button variant="destructive" size="sm">
              <Trash2 className="mr-2 h-4 w-4" />
              {t("disconnect")}
            </Button>
          </ConfirmDialog>
        </div>
      </div>

      {/* Connection Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("connection_info")}</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-muted-foreground">{t("table.status")}</dt>
              <dd className="mt-1">
                <StatusDot status={STATUS_MAP[connection.status] || "inactive"} label={connection.status} />
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("table.account")}</dt>
              <dd className="mt-1">{connection.account_identifier || "-"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("table.connected")}</dt>
              <dd className="mt-1">{formatDate(connection.created_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("last_used")}</dt>
              <dd className="mt-1">{connection.last_used_at ? formatDateTime(connection.last_used_at) : "-"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("table.tools")}</dt>
              <dd className="mt-1">
                <Badge variant="secondary">{connection.tools_count} tools</Badge>
              </dd>
            </div>
            {connection.health_checked_at && (
              <div>
                <dt className="text-muted-foreground">{t("last_health_check")}</dt>
                <dd className="mt-1">{formatDateTime(connection.health_checked_at)}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>

      {/* Available Tools */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("available_tools")}</CardTitle>
          <CardDescription>{t("tools_description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {!tools || tools.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              {t("no_tools")}
            </p>
          ) : (
            <div className="space-y-2">
              {tools.map((tool) => (
                <div key={tool.name} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono font-medium">{tool.name}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{tool.description}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
