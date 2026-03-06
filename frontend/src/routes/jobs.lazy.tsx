import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
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
}

function CancelButton({ job }: { job: Job }) {
  const cancelJob = useCancelJob()

  if (job.status !== "pending" && job.status !== "processing") return null

  return (
    <ConfirmDialog
      title="Cancel Job"
      description={`Cancel job "${job.type}"? This cannot be undone.`}
      variant="destructive"
      confirmLabel="Cancel Job"
      onConfirm={async () => {
        try {
          await cancelJob.mutateAsync(job.id)
          toast.success("Job cancelled")
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    >
      <Button variant="ghost" size="sm">
        Cancel
      </Button>
    </ConfirmDialog>
  )
}

const columns: ColumnDef<Job>[] = [
  { accessorKey: "type", header: "Type" },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={statusVariant[row.original.status]}>{row.original.status}</Badge>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.created_at),
  },
  {
    accessorKey: "completed_at",
    header: "Completed",
    cell: ({ row }) =>
      row.original.completed_at ? formatDateTime(row.original.completed_at) : "\u2014",
  },
  {
    accessorKey: "error",
    header: "Error",
    cell: ({ row }) =>
      row.original.error ? (
        <span className="text-xs text-destructive" title={row.original.error}>
          Error
        </span>
      ) : null,
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <CancelButton job={row.original} />,
  },
]

function JobsPage() {
  const queryResult = useJobs()
  const [createOpen, setCreateOpen] = useState(false)
  const [jobType, setJobType] = useState("")
  const createJob = useCreateJob()

  const handleCreate = async () => {
    if (!jobType.trim()) return
    try {
      await createJob.mutateAsync({ type: jobType.trim() })
      toast.success("Job created")
      setCreateOpen(false)
      setJobType("")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <AuthGuard>
      <ResourcePage
        title="Jobs"
        description="Manage async processing jobs."
        queryResult={queryResult}
        columns={columns}
        searchKey="type"
        searchPlaceholder="Search jobs..."
        emptyState={{
          icon: Briefcase,
          title: "No jobs yet",
          description: "Create a job to start processing.",
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Job
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Job
          </Button>
        }
      />
      <FormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) setJobType("")
        }}
        title="Create Job"
        description="Specify the job type to create."
        isPending={createJob.isPending}
        onSubmit={handleCreate}
        submitLabel="Create"
      >
        <div className="space-y-2">
          <Label htmlFor="job-type">Job type</Label>
          <Input
            id="job-type"
            placeholder="e.g. data-export, report"
            value={jobType}
            onChange={(e) => setJobType(e.target.value)}
            maxLength={50}
            autoFocus
          />
        </div>
      </FormDialog>
    </AuthGuard>
  )
}
