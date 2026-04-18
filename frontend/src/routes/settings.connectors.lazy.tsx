import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Plug, Trash2, TestTube } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { StatusDot } from "@/components/status-dot"
import {
  useConnectors,
  useConnections,
  useCreateConnection,
  useDeleteConnection,
  useTestConnection,
  useStartOAuth,
  type ConnectorDefinition,
  type TenantConnection,
} from "@/hooks/use-connectors"
import { parseApiError } from "@/lib/api-client"
import { formatDate } from "@/lib/format"

export const Route = createLazyFileRoute("/settings/connectors")({
  component: SettingsConnectorsPage,
})

// ── Category Config ─────────────────────────────────────

const CATEGORIES = [
  { value: "", label: "All" },
  { value: "productivity", label: "Productivity" },
  { value: "developer_tools", label: "Developer Tools" },
  { value: "communication", label: "Communication" },
  { value: "cloud_storage", label: "Cloud Storage" },
  { value: "project_management", label: "Project Management" },
  { value: "crm", label: "CRM" },
  { value: "custom", label: "Custom" },
] as const

const STATUS_MAP: Record<string, "active" | "inactive" | "error" | "draft"> = {
  active: "active",
  degraded: "draft",
  expired: "error",
  disconnected: "inactive",
  error: "error",
}

// ── Connection Actions ──────────────────────────────────

function ConnectionActions({ connection }: { connection: TenantConnection }) {
  const { t } = useTranslation("connectors")
  const { t: tc } = useTranslation("common")
  const testConn = useTestConnection()
  const deleteConn = useDeleteConnection()

  const handleTest = async () => {
    try {
      const result = await testConn.mutateAsync(connection.id)
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
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="sm"
        onClick={handleTest}
        disabled={testConn.isPending}
        title={t("test_connection")}
      >
        <TestTube className="h-4 w-4" />
      </Button>
      <ConfirmDialog
        title={t("disconnect_title")}
        description={t("disconnect_desc", { name: connection.display_name })}
        variant="destructive"
        confirmLabel={tc("buttons.delete")}
        onConfirm={async () => {
          try {
            await deleteConn.mutateAsync(connection.id)
            toast.success(t("disconnect_success"))
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <Button variant="ghost" size="sm" title={t("disconnect")}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </ConfirmDialog>
    </div>
  )
}

// ── Source Badge ────────────────────────────────────────
// Subtle pill indicating where a connector definition came from. Helps
// operators distinguish platform-managed YAML connectors from auto-synced
// managed-broker catalogs (Composio, etc.) without requiring extra clicks.

function SourceBadge({ source }: { source: ConnectorDefinition["source"] }) {
  const config: Record<
    ConnectorDefinition["source"],
    { label: string; className: string } | null
  > = {
    yaml: { label: "Platform", className: "bg-primary/10 text-primary border-primary/20" },
    plugin: { label: "Plugin", className: "bg-primary/10 text-primary border-primary/20" },
    composio: { label: "Composio", className: "bg-muted text-muted-foreground border-border" },
    tenant_mcp: { label: "Custom MCP", className: "bg-muted text-muted-foreground border-border" },
  }
  const entry = config[source]
  if (!entry) return null
  return (
    <Badge variant="outline" className={`text-[10px] uppercase tracking-wider ${entry.className}`}>
      {entry.label}
    </Badge>
  )
}

// ── Connector Card (Marketplace) ────────────────────────

function ConnectorCard({
  connector,
  isConnected,
  onConnect,
}: {
  connector: ConnectorDefinition
  isConnected: boolean
  onConnect: (connector: ConnectorDefinition) => void
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Plug className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">{connector.name}</CardTitle>
          </div>
          {isConnected && (
            <Badge variant="default" className="text-xs">Connected</Badge>
          )}
        </div>
        <CardDescription className="line-clamp-2 text-xs">
          {connector.description}
        </CardDescription>
      </CardHeader>
      <CardFooter className="mt-auto pt-0 flex items-center justify-between">
        <div className="flex gap-1">
          <Badge variant="outline" className="text-xs">{connector.category.replace("_", " ")}</Badge>
          <SourceBadge source={connector.source} />
        </div>
        <Button
          size="sm"
          variant={isConnected ? "outline" : "default"}
          onClick={() => onConnect(connector)}
          disabled={isConnected}
        >
          {isConnected ? "Connected" : "Connect"}
        </Button>
      </CardFooter>
    </Card>
  )
}

// ── API Key Connect Dialog ──────────────────────────────

function ApiKeyConnectDialog({
  connector,
  open,
  onOpenChange,
}: {
  connector: ConnectorDefinition | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation("connectors")
  const { t: tc } = useTranslation("common")
  const createConn = useCreateConnection()
  const [displayName, setDisplayName] = useState("")
  const [apiKey, setApiKey] = useState("")

  const handleCreate = async () => {
    if (!connector) return
    try {
      await createConn.mutateAsync({
        connector_slug: connector.slug,
        display_name: displayName || connector.name,
        api_key: apiKey || undefined,
      })
      toast.success(t("connect_success"))
      onOpenChange(false)
      setDisplayName("")
      setApiKey("")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) { setDisplayName(""); setApiKey("") }
      }}
      title={t("connect_dialog_title", { name: connector?.name })}
      description={t("connect_dialog_desc")}
      isPending={createConn.isPending}
      onSubmit={handleCreate}
      submitLabel={tc("buttons.create")}
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="conn-name">{t("display_name_label")}</Label>
          <Input
            id="conn-name"
            placeholder={connector?.name}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            autoFocus
          />
        </div>
        {connector?.auth_type === "api_key" && (
          <div className="space-y-2">
            <Label htmlFor="conn-key">{t("api_key_label")}</Label>
            <Input
              id="conn-key"
              type="password"
              placeholder={t("api_key_placeholder")}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
        )}
      </div>
    </FormDialog>
  )
}

// ── Column Definitions ──────────────────────────────────

function useConnectionColumns(): ColumnDef<TenantConnection>[] {
  const { t } = useTranslation("connectors")
  const { t: tc } = useTranslation("common")

  return [
    {
      accessorKey: "display_name",
      header: t("table.name"),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Plug className="h-4 w-4 text-muted-foreground" />
          <div>
            <div className="font-medium">{row.original.display_name}</div>
            <div className="text-xs text-muted-foreground">{row.original.connector_name}</div>
          </div>
        </div>
      ),
    },
    {
      accessorKey: "account_identifier",
      header: t("table.account"),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.account_identifier || "-"}
        </span>
      ),
    },
    {
      accessorKey: "status",
      header: t("table.status"),
      cell: ({ row }) => (
        <StatusDot status={STATUS_MAP[row.original.status] || "inactive"} label={row.original.status} />
      ),
    },
    {
      accessorKey: "tools_count",
      header: t("table.tools"),
      cell: ({ row }) => (
        <Badge variant="secondary">{row.original.tools_count} tools</Badge>
      ),
    },
    {
      accessorKey: "created_at",
      header: t("table.connected"),
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <ConnectionActions connection={row.original} />,
    },
  ]
}

// ── Main Page ───────────────────────────────────────────

function SettingsConnectorsPage() {
  const { t } = useTranslation("connectors")
  const connectionsQuery = useConnections()
  const [category, setCategory] = useState("")
  const connectorsQuery = useConnectors(category || undefined)
  const startOAuth = useStartOAuth()
  const columns = useConnectionColumns()

  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false)
  const [selectedConnector, setSelectedConnector] = useState<ConnectorDefinition | null>(null)

  const connections = connectionsQuery.data?.items || []
  const connectors = connectorsQuery.data?.items || []
  const connectedSlugs = new Set(connections.map((c) => c.connector_slug))

  const handleConnect = async (connector: ConnectorDefinition) => {
    if (connector.auth_type === "oauth2") {
      try {
        const result = await startOAuth.mutateAsync(connector.slug)
        window.location.href = result.auth_url
      } catch (err) {
        const e = await parseApiError(err)
        toast.error(e.detail)
      }
    } else {
      setSelectedConnector(connector)
      setApiKeyDialogOpen(true)
    }
  }

  return (
    <>
      <ResourcePage
        title={t("title")}
        description={t("description")}
        queryResult={connectionsQuery}
        columns={columns}
        searchKey="display_name"
        searchPlaceholder={t("search_connections")}
        emptyState={{
          icon: Plug,
          title: t("no_connections"),
          description: t("no_connections_desc"),
        }}
        headerContent={
          <div className="mt-6">
            <h3 className="text-lg font-semibold mb-3">{t("available_connectors")}</h3>
            <Tabs value={category} onValueChange={setCategory} className="mb-4">
              <TabsList className="flex-wrap h-auto gap-1">
                {CATEGORIES.map((cat) => (
                  <TabsTrigger key={cat.value} value={cat.value} className="text-xs">
                    {cat.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {connectors.map((connector) => (
                <ConnectorCard
                  key={connector.slug}
                  connector={connector}
                  isConnected={connectedSlugs.has(connector.slug)}
                  onConnect={handleConnect}
                />
              ))}
              {connectorsQuery.isLoading && (
                <div className="col-span-full text-center py-8 text-muted-foreground text-sm">
                  Loading connectors...
                </div>
              )}
              {!connectorsQuery.isLoading && connectors.length === 0 && (
                <div className="col-span-full text-center py-8 text-muted-foreground text-sm">
                  {t("no_connectors_found")}
                </div>
              )}
            </div>
          </div>
        }
      />
      <ApiKeyConnectDialog
        connector={selectedConnector}
        open={apiKeyDialogOpen}
        onOpenChange={setApiKeyDialogOpen}
      />
    </>
  )
}
