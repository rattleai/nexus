import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Briefcase, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { useJobs, useCreateJob, useCancelJob } from "@/hooks/use-jobs"
import { parseApiError } from "@/lib/api-client"
import { formatDateTime } from "@/lib/format"
import type { Job, JobStatus } from "@/types/api"

export const Route = createLazyFileRoute("/jobs")({
  component: JobsPage,
})

const statusVariant: Record<JobStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  processing: "secondary",
  completed: "default",
  failed: "destructive",
  cancelled: "outline",
}

function CancelButton({ job }: { job: Job }) {
  const { t } = useTranslation("jobs")
  const { t: tc } = useTranslation("common")
  const cancelJob = useCancelJob()

  if (job.status !== "pending" && job.status !== "processing") return null

  return (
    <ConfirmDialog
      title={t("cancel_title")}
      description={t("cancel_desc", { jobType: job.type })}
      variant="destructive"
      confirmLabel={t("cancel_button")}
      onConfirm={async () => {
        try {
          await cancelJob.mutateAsync(job.id)
          toast.success(t("cancel_success"))
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    >
      <Button variant="ghost" size="sm">
        {tc("buttons.cancel")}
      </Button>
    </ConfirmDialog>
  )
}

function useJobColumns(): ColumnDef<Job>[] {
  const { t } = useTranslation("jobs")
  const { t: tc } = useTranslation("common")

  return [
    { accessorKey: "type", header: t("table.type") },
    {
      accessorKey: "status",
      header: t("table.status"),
      cell: ({ row }) => (
        <Badge variant={statusVariant[row.original.status]}>{tc(`status.${row.original.status}` as never)}</Badge>
      ),
    },
    {
      accessorKey: "created_at",
      header: t("table.created"),
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      accessorKey: "completed_at",
      header: t("table.completed"),
      cell: ({ row }) =>
        row.original.completed_at ? formatDateTime(row.original.completed_at) : "\u2014",
    },
    {
      accessorKey: "error",
      header: t("table.error"),
      cell: ({ row }) =>
        row.original.error ? (
          <span className="text-xs text-destructive" title={row.original.error}>
            {t("table.error")}
          </span>
        ) : null,
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <CancelButton job={row.original} />,
    },
  ]
}

function JobsPage() {
  return (
    <AuthGuard>
      <JobsPageContent />
    </AuthGuard>
  )
}

function JobsPageContent() {
  const { t } = useTranslation("jobs")
  const { t: tc } = useTranslation("common")
  const queryResult = useJobs()
  const [createOpen, setCreateOpen] = useState(false)
  const [jobType, setJobType] = useState("")
  const createJob = useCreateJob()
  const columns = useJobColumns()

  const handleCreate = async () => {
    if (!jobType.trim()) return
    try {
      await createJob.mutateAsync({ type: jobType.trim() })
      toast.success(t("create_success"))
      setCreateOpen(false)
      setJobType("")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <>
      <ResourcePage
        title={t("title")}
        description={t("description")}
        queryResult={queryResult}
        columns={columns}
        searchKey="type"
        searchPlaceholder={t("search_placeholder")}
        titleColumn="type"
        hideColumns={["actions"]}
        emptyState={{
          icon: Briefcase,
          title: t("no_jobs"),
          description: t("no_jobs_desc"),
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("create_job")}
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t("create_job")}
          </Button>
        }
      />
      <FormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) setJobType("")
        }}
        title={t("create_dialog_title")}
        description={t("create_dialog_desc")}
        isPending={createJob.isPending}
        onSubmit={handleCreate}
        submitLabel={tc("buttons.create")}
      >
        <div className="space-y-2">
          <Label htmlFor="job-type">{t("job_type_label")}</Label>
          <Input
            id="job-type"
            placeholder={t("job_type_placeholder")}
            value={jobType}
            onChange={(e) => setJobType(e.target.value)}
            maxLength={50}
            autoFocus
          />
        </div>
      </FormDialog>
    </>
  )
}
