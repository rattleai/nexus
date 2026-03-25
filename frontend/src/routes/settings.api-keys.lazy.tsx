import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Key, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StatusDot } from "@/components/status-dot"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { CopyButton } from "@/components/copy-button"
import { FormDialog } from "@/components/form-dialog"
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/use-api-keys"
import { parseApiError } from "@/lib/api-client"
import { formatDate } from "@/lib/format"
import type { ApiKey } from "@/types/api"

export const Route = createLazyFileRoute("/settings/api-keys")({
  component: SettingsApiKeysPage,
})

function useApiKeyColumns(): ColumnDef<ApiKey>[] {
  const { t } = useTranslation("api_keys")
  const { t: tc } = useTranslation("common")

  return [
    { accessorKey: "name", header: t("table.name") },
    {
      accessorKey: "active",
      header: t("table.status"),
      cell: ({ row }) => (
        <StatusDot
          variant={row.original.active ? "active" : "inactive"}
          label={row.original.active ? tc("status.active") : tc("status.revoked")}
          labelClassName="text-xs text-muted-foreground"
        />
      ),
    },
    {
      accessorKey: "scopes",
      header: t("table.scopes"),
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.scopes?.join(", ") || t("all_scopes")}
        </span>
      ),
    },
    {
      accessorKey: "rate_limit",
      header: t("table.rate_limit"),
      cell: ({ row }) =>
        row.original.rate_limit
          ? t("rate_limit_per_min", { limit: row.original.rate_limit })
          : `${tc("status.unlimited")}/min`,
    },
    {
      accessorKey: "created_at",
      header: t("table.created"),
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <RevokeButton apiKey={row.original} />,
    },
  ]
}

function RevokeButton({ apiKey }: { apiKey: ApiKey }) {
  const { t } = useTranslation("api_keys")
  const { t: tc } = useTranslation("common")
  const revokeKey = useRevokeApiKey()

  if (!apiKey.active) return null

  return (
    <ConfirmDialog
      title={t("revoke_title")}
      description={t("revoke_desc", { keyName: apiKey.name })}
      variant="destructive"
      confirmLabel={tc("buttons.revoke")}
      onConfirm={async () => {
        try {
          await revokeKey.mutateAsync(apiKey.id)
          toast.success(t("revoke_success"))
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    >
      <Button variant="ghost" size="sm">
        {tc("buttons.revoke")}
      </Button>
    </ConfirmDialog>
  )
}

function SettingsApiKeysPage() {
  const { t } = useTranslation("api_keys")
  const queryResult = useApiKeys()
  const [createOpen, setCreateOpen] = useState(false)
  const columns = useApiKeyColumns()

  return (
    <>
      <ResourcePage
        title={t("title")}
        description={t("description")}
        queryResult={queryResult}
        columns={columns}
        searchKey="name"
        searchPlaceholder={t("search_placeholder")}
        emptyState={{
          icon: Key,
          title: t("no_keys"),
          description: t("no_keys_desc"),
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("create_key")}
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t("create_key")}
          </Button>
        }
      />
      <CreateKeyDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  )
}

function CreateKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation("api_keys")
  const { t: tc } = useTranslation("common")
  const [name, setName] = useState("")
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const createKey = useCreateApiKey()

  const handleCreate = async () => {
    try {
      const result = await createKey.mutateAsync({ name: name || "default" })
      setCreatedKey(result.raw_key)
      toast.success(t("create_success"))
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
    setName("")
    setCreatedKey(null)
  }

  if (createdKey) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("key_created_title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("key_created_desc")}</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 p-3 bg-muted rounded text-sm break-all font-mono">
                {createdKey}
              </code>
              <CopyButton value={createdKey} />
            </div>
            <Button onClick={handleClose} className="w-full">
              {tc("buttons.done")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={handleClose}
      title={t("create_dialog_title")}
      description={t("create_dialog_desc")}
      isPending={createKey.isPending}
      onSubmit={handleCreate}
      submitLabel={tc("buttons.create")}
    >
      <div className="space-y-2">
        <Label htmlFor="key-name">{t("key_name_label")}</Label>
        <Input
          id="key-name"
          placeholder={t("key_name_placeholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={255}
          autoFocus
        />
      </div>
    </FormDialog>
  )
}
