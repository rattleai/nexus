import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
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

const EVENT_OPTIONS = [
  { value: "job.created", label: "Job Created" },
  { value: "job.completed", label: "Job Completed" },
  { value: "job.failed", label: "Job Failed" },
  { value: "file.uploaded", label: "File Uploaded" },
  { value: "file.deleted", label: "File Deleted" },
  { value: "member.invited", label: "Member Invited" },
  { value: "member.removed", label: "Member Removed" },
  { value: "subscription.created", label: "Subscription Created" },
  { value: "subscription.canceled", label: "Subscription Canceled" },
  { value: "export.completed", label: "Export Completed" },
]

function ActiveToggle({ endpoint }: { endpoint: WebhookEndpoint }) {
  const updateWebhook = useUpdateWebhook()

  return (
    <Switch
      checked={endpoint.active}
      onCheckedChange={async (active) => {
        try {
          await updateWebhook.mutateAsync({ id: endpoint.id, active })
          toast.success(active ? "Webhook enabled" : "Webhook disabled")
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    />
  )
}

function WebhookActions({ endpoint }: { endpoint: WebhookEndpoint }) {
  const [historyOpen, setHistoryOpen] = useState(false)
  const testWebhook = useTestWebhook()
  const deleteWebhook = useDeleteWebhook()

  const handleTest = async () => {
    try {
      await testWebhook.mutateAsync(endpoint.id)
      toast.success("Test delivery sent")
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
        title="Send test"
      >
        <Send className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setHistoryOpen(true)} title="Delivery history">
        <History className="h-4 w-4" />
      </Button>
      <ConfirmDialog
        title="Delete Webhook"
        description={`Delete the webhook for ${endpoint.url}? This cannot be undone.`}
        variant="destructive"
        confirmLabel="Delete"
        onConfirm={async () => {
          try {
            await deleteWebhook.mutateAsync(endpoint.id)
            toast.success("Webhook deleted")
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
  const { data, isLoading } = useWebhookDeliveries(open ? endpointId : "")

  const deliveries: WebhookDelivery[] = data
    ? Array.isArray(data) ? data : data.items
    : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Delivery History</DialogTitle>
          <DialogDescription className="truncate">{url}</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <LoadingState variant="skeleton" rows={3} />
        ) : deliveries.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No deliveries yet.</p>
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
                    {d.attempts} attempt(s)
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

const columns: ColumnDef<WebhookEndpoint>[] = [
  {
    accessorKey: "url",
    header: "URL",
    cell: ({ row }) => (
      <span className="text-sm font-mono truncate max-w-[200px] block" title={row.original.url}>
        {row.original.url}
      </span>
    ),
  },
  {
    accessorKey: "events",
    header: "Events",
    cell: ({ row }) => (
      <Badge variant="secondary">{row.original.events.length} event(s)</Badge>
    ),
  },
  {
    accessorKey: "active",
    header: "Active",
    cell: ({ row }) => <ActiveToggle endpoint={row.original} />,
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ row }) => formatDate(row.original.created_at),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <WebhookActions endpoint={row.original} />,
  },
]

function WebhooksPage() {
  const queryResult = useWebhooks()
  const createWebhook = useCreateWebhook()
  const [createOpen, setCreateOpen] = useState(false)
  const [newUrl, setNewUrl] = useState("")
  const [newEvents, setNewEvents] = useState<string[]>([])

  const handleCreate = async () => {
    if (!newUrl.trim() || newEvents.length === 0) {
      toast.error("URL and at least one event are required")
      return
    }
    try {
      await createWebhook.mutateAsync({ url: newUrl.trim(), events: newEvents })
      toast.success("Webhook created")
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
        title="Webhooks"
        description="Receive real-time notifications for events in your workspace."
        queryResult={queryResult}
        columns={columns}
        searchKey="url"
        searchPlaceholder="Search webhooks..."
        emptyState={{
          icon: Webhook,
          title: "No webhooks yet",
          description: "Create a webhook to receive event notifications.",
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Webhook
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Webhook
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
        title="Create Webhook"
        description="Configure a URL to receive event notifications."
        isPending={createWebhook.isPending}
        onSubmit={handleCreate}
        submitLabel="Create"
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="webhook-url">Endpoint URL</Label>
            <Input
              id="webhook-url"
              type="url"
              placeholder="https://example.com/webhook"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label>Events</Label>
            <MultiSelect
              options={EVENT_OPTIONS}
              selected={newEvents}
              onChange={setNewEvents}
              placeholder="Select events..."
              searchPlaceholder="Search events..."
            />
          </div>
        </div>
      </FormDialog>
    </AuthGuard>
  )
}
