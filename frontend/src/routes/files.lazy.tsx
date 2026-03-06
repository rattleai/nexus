import { createLazyFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { FileIcon, Download, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { FileUpload } from "@/components/file-upload"
import { useFiles, useUploadFile, useDeleteFile } from "@/hooks/use-files"
import { parseApiError } from "@/lib/api-client"
import { formatDate, formatBytes } from "@/lib/format"
import type { FileRecord } from "@/types/api"

export const Route = createLazyFileRoute("/files")({
  component: FilesPage,
})

function DeleteButton({ file }: { file: FileRecord }) {
  const deleteFile = useDeleteFile()

  return (
    <ConfirmDialog
      title="Delete File"
      description={`Are you sure you want to delete "${file.filename}"? This cannot be undone.`}
      variant="destructive"
      confirmLabel="Delete"
      onConfirm={async () => {
        try {
          await deleteFile.mutateAsync(file.id)
          toast.success("File deleted")
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
  )
}

function FileActions({ file }: { file: FileRecord }) {
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => window.open(`/api/v1/files/${file.id}/download`)}
      >
        <Download className="h-4 w-4" />
      </Button>
      <DeleteButton file={file} />
    </div>
  )
}

const columns: ColumnDef<FileRecord>[] = [
  { accessorKey: "filename", header: "Filename" },
  { accessorKey: "content_type", header: "Type" },
  {
    accessorKey: "size_bytes",
    header: "Size",
    cell: ({ row }) => formatBytes(row.original.size_bytes),
  },
  {
    accessorKey: "created_at",
    header: "Uploaded",
    cell: ({ row }) => formatDate(row.original.created_at),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <FileActions file={row.original} />,
  },
]

function FilesPage() {
  const queryResult = useFiles()
  const uploadFile = useUploadFile()

  const handleUpload = async (files: File[]) => {
    try {
      await Promise.all(files.map((f) => uploadFile.mutateAsync(f)))
      toast.success(`${files.length} file(s) uploaded`)
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <AuthGuard>
      <ResourcePage
        title="Files"
        description="Upload and manage your files."
        queryResult={queryResult}
        columns={columns}
        searchKey="filename"
        searchPlaceholder="Search files..."
        emptyState={{
          icon: FileIcon,
          title: "No files yet",
          description: "Upload a file to get started.",
        }}
        headerContent={
          <Card>
            <CardHeader>
              <CardTitle>Upload Files</CardTitle>
            </CardHeader>
            <CardContent>
              <FileUpload
                onUpload={handleUpload}
                multiple
                disabled={uploadFile.isPending}
              />
            </CardContent>
          </Card>
        }
      />
    </AuthGuard>
  )
}
