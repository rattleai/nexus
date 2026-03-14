import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Webhook, Plus, History, Send, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { MultiSelect } from "@/components/multi-select"
import { LoadingState } from "@/components/loading-state"
import {
  useWebhooks,
  useCreateWebhook,
  useUpdateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useWebhookDeliveries,
} from "@/hooks/use-webhooks"
import { parseApiError } from "@/lib/api-client"
import { formatDate, formatDateTime } from "@/lib/format"
import type { WebhookEndpoint, WebhookDelivery } from "@/types/api"

export const Route = createLazyFileRoute("/webhooks")({
  component: WebhooksPage,
})

function useEventOptions() {
  const { t } = useTranslation("webhooks")
  return [
    { value: "job.created", label: t("events.job_created") },
    { value: "job.completed", label: t("events.job_completed") },
    { value: "job.failed", label: t("events.job_failed") },
    { value: "file.uploaded", label: t("events.file_uploaded") },
    { value: "file.deleted", label: t("events.file_deleted") },
    { value: "member.invited", label: t("events.member_invited") },
    { value: "member.removed", label: t("events.member_removed") },
    { value: "subscription.created", label: t("events.subscription_created") },
    { value: "subscription.canceled", label: t("events.subscription_canceled") },
    { value: "export.completed", label: t("events.export_completed") },
  ]
}

function ActiveToggle({ endpoint }: { endpoint: WebhookEndpoint }) {
  const { t } = useTranslation("webhooks")
  const updateWebhook = useUpdateWebhook()

  return (
    <Switch
      checked={endpoint.active}
      onCheckedChange={async (active) => {
        try {
          await updateWebhook.mutateAsync({ id: endpoint.id, active })
          toast.success(active ? t("enabled") : t("disabled"))
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    />
  )
}

function WebhookActions({ endpoint }: { endpoint: WebhookEndpoint }) {
  const { t } = useTranslation("webhooks")
  const { t: tc } = useTranslation("common")
  const [historyOpen, setHistoryOpen] = useState(false)
  const testWebhook = useTestWebhook()
  const deleteWebhook = useDeleteWebhook()

  const handleTest = async () => {
    try {
      await testWebhook.mutateAsync(endpoint.id)
      toast.success(t("test_delivery"))
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
        disabled={testWebhook.isPending}
        title={t("send_test")}
      >
        <Send className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setHistoryOpen(true)} title={t("delivery_history_tooltip")}>
        <History className="h-4 w-4" />
      </Button>
      <ConfirmDialog
        title={t("delete_title")}
        description={t("delete_desc", { url: endpoint.url })}
        variant="destructive"
        confirmLabel={tc("buttons.delete")}
        onConfirm={async () => {
          try {
            await deleteWebhook.mutateAsync(endpoint.id)
            toast.success(t("delete_success"))
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <Button variant="ghost" size="sm">
          <Trash2 className="h-4 w-4" />
        </Button>
      </ConfirmDialog>
      <DeliveryHistoryDialog
        endpointId={endpoint.id}
        url={endpoint.url}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
      />
    </div>
  )
}

function DeliveryHistoryDialog({
  endpointId,
  url,
  open,
  onOpenChange,
}: {
  endpointId: string
  url: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation("webhooks")
  const { data, isLoading } = useWebhookDeliveries(open ? endpointId : "")

  const deliveries: WebhookDelivery[] = data
    ? Array.isArray(data) ? data : data.items
    : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("delivery_history")}</DialogTitle>
          <DialogDescription className="truncate">{url}</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <LoadingState variant="skeleton" rows={3} />
        ) : deliveries.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">{t("no_deliveries")}</p>
        ) : (
          <div className="space-y-3">
            {deliveries.map((d) => (
              <div key={d.id} className="flex items-center justify-between rounded-md border p-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={d.success ? "default" : "destructive"}>
                      {d.status_code ?? "N/A"}
                    </Badge>
                    <span className="text-sm font-medium">{d.event_type}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {t("delivery_attempts", { count: d.attempts })}
                    {d.delivered_at && <> &middot; {formatDateTime(d.delivered_at)}</>}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function useWebhookColumns(): ColumnDef<WebhookEndpoint>[] {
  const { t } = useTranslation("webhooks")
  const { t: tc } = useTranslation("common")

  return [
    {
      accessorKey: "url",
      header: t("table.url"),
      cell: ({ row }) => (
        <span className="text-sm font-mono truncate max-w-[200px] block" title={row.original.url}>
          {row.original.url}
        </span>
      ),
    },
    {
      accessorKey: "events",
      header: t("table.events"),
      cell: ({ row }) => (
        <Badge variant="secondary">{t("event_count", { count: row.original.events.length })}</Badge>
      ),
    },
    {
      accessorKey: "active",
      header: t("table.active"),
      cell: ({ row }) => <ActiveToggle endpoint={row.original} />,
    },
    {
      accessorKey: "created_at",
      header: t("table.created"),
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <WebhookActions endpoint={row.original} />,
    },
  ]
}

function WebhooksPage() {
  const { t } = useTranslation("webhooks")
  const { t: tc } = useTranslation("common")
  const { t: tv } = useTranslation("validation")
  const queryResult = useWebhooks()
  const createWebhook = useCreateWebhook()
  const [createOpen, setCreateOpen] = useState(false)
  const [newUrl, setNewUrl] = useState("")
  const [newEvents, setNewEvents] = useState<string[]>([])
  const columns = useWebhookColumns()
  const eventOptions = useEventOptions()

  const handleCreate = async () => {
    if (!newUrl.trim() || newEvents.length === 0) {
      toast.error(tv("url_and_events_required"))
      return
    }
    try {
      await createWebhook.mutateAsync({ url: newUrl.trim(), events: newEvents })
      toast.success(t("create_success"))
      setCreateOpen(false)
      setNewUrl("")
      setNewEvents([])
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <AuthGuard>
      <ResourcePage
        title={t("title")}
        description={t("description")}
        queryResult={queryResult}
        columns={columns}
        searchKey="url"
        searchPlaceholder={t("search_placeholder")}
        emptyState={{
          icon: Webhook,
          title: t("no_webhooks"),
          description: t("no_webhooks_desc"),
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("create_webhook")}
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t("create_webhook")}
          </Button>
        }
      />
      <FormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) {
            setNewUrl("")
            setNewEvents([])
          }
        }}
        title={t("create_dialog_title")}
        description={t("create_dialog_desc")}
        isPending={createWebhook.isPending}
        onSubmit={handleCreate}
        submitLabel={tc("buttons.create")}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="webhook-url">{t("endpoint_url_label")}</Label>
            <Input
              id="webhook-url"
              type="url"
              placeholder={t("endpoint_url_placeholder")}
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label>{t("events_label")}</Label>
            <MultiSelect
              options={eventOptions}
              selected={newEvents}
              onChange={setNewEvents}
              placeholder={t("events_placeholder")}
              searchPlaceholder={t("events_search_placeholder")}
            />
          </div>
        </div>
      </FormDialog>
    </AuthGuard>
  )
}
