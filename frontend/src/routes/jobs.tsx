import { useState } from "react"
import { createFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useJobs, useCreateJob, useCancelJob } from "@/hooks/use-jobs"
import { useAuth } from "@/hooks/use-auth"
import { ApiKeyPrompt } from "@/components/auth/api-key-prompt"
import type { JobStatus } from "@/types/api"

export const Route = createFileRoute("/jobs")({
  component: JobsPage,
})

function JobsPage() {
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <ApiKeyPrompt />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Jobs</h1>
        <CreateJobButton />
      </div>
      <JobsTable />
    </div>
  )
}

function CreateJobButton() {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState("")
  const createJob = useCreateJob()

  const handleCreate = async () => {
    if (!type.trim()) return
    try {
      await createJob.mutateAsync({ type: type.trim() })
      toast.success("Job created")
      setOpen(false)
      setType("")
    } catch {
      toast.error("Failed to create job")
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>Create Job</Button>
      <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setType("") }}>
        <DialogHeader>
          <DialogTitle>Create Job</DialogTitle>
        </DialogHeader>
        <DialogContent>
          <Input
            placeholder="Job type (e.g. data-export, report)"
            value={type}
            onChange={(e) => setType(e.target.value)}
            autoFocus
          />
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={createJob.isPending || !type.trim()}>
            {createJob.isPending ? "Creating..." : "Create"}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  )
}

const statusColor: Record<JobStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  processing: "secondary",
  completed: "default",
  failed: "destructive",
}

function JobsTable() {
  const { data, isLoading, error } = useJobs()
  const cancelJob = useCancelJob()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500">
          Failed to load jobs
        </CardContent>
      </Card>
    )
  }

  const jobs = data?.items ?? []

  if (!jobs.length) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500">
          No jobs yet. Create one to get started.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Jobs</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Completed</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="font-medium">{job.type}</TableCell>
                <TableCell>
                  <Badge variant={statusColor[job.status]}>
                    {job.status}
                  </Badge>
                </TableCell>
                <TableCell>{new Date(job.created_at).toLocaleString()}</TableCell>
                <TableCell>
                  {job.completed_at ? new Date(job.completed_at).toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-right">
                  {(job.status === "pending" || job.status === "processing") && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        cancelJob.mutate(job.id, {
                          onSuccess: (r) => {
                            if (r.cancelled) toast.success("Job cancelled")
                            else toast.info("Job could not be cancelled")
                          },
                          onError: () => toast.error("Failed to cancel job"),
                        })
                      }}
                    >
                      Cancel
                    </Button>
                  )}
                  {job.error && (
                    <span className="text-xs text-destructive ml-2" title={job.error}>
                      Error
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
