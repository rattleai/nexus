import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
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
  const { t } = useTranslation("files")
  const { t: tc } = useTranslation("common")
  const deleteFile = useDeleteFile()

  return (
    <ConfirmDialog
      title={t("delete_title")}
      description={t("delete_desc", { filename: file.filename })}
      variant="destructive"
      confirmLabel={tc("buttons.delete")}
      onConfirm={async () => {
        try {
          await deleteFile.mutateAsync(file.id)
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

function useFileColumns(): ColumnDef<FileRecord>[] {
  const { t } = useTranslation("files")
  const { t: tc } = useTranslation("common")

  return [
    { accessorKey: "filename", header: t("table.filename") },
    { accessorKey: "content_type", header: t("table.type") },
    {
      accessorKey: "size_bytes",
      header: t("table.size"),
      cell: ({ row }) => formatBytes(row.original.size_bytes),
    },
    {
      accessorKey: "created_at",
      header: t("table.uploaded"),
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <FileActions file={row.original} />,
    },
  ]
}

function FilesPage() {
  const { t } = useTranslation("files")
  const queryResult = useFiles()
  const uploadFile = useUploadFile()
  const columns = useFileColumns()

  const handleUpload = async (files: File[]) => {
    try {
      await Promise.all(files.map((f) => uploadFile.mutateAsync(f)))
      toast.success(t("upload_success", { count: files.length }))
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
        searchKey="filename"
        searchPlaceholder={t("search_placeholder")}
        emptyState={{
          icon: FileIcon,
          title: t("no_files"),
          description: t("no_files_desc"),
        }}
        headerContent={
          <Card>
            <CardHeader>
              <CardTitle>{t("upload_title")}</CardTitle>
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
