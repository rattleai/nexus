import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  ChevronRight,
  Cloud,
  File as FileIcon,
  Folder,
  HardDrive,
  Loader2,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/lib/format"
import { useConnections, type TenantConnection } from "@/hooks/use-connectors"
import {
  CLOUD_DRIVE_SLUGS,
  isCloudDriveSlug,
  useCreateDataSourceFromDrive,
  useDriveListing,
  type DriveItem,
} from "@/hooks/use-cloud-drive"

// Slugs rendered as disabled ("Coming soon") when the connection is
// Composio-brokered — backend returns 501 for those in v1.
// The flag lives on ``TenantConnection.config_overrides?.broker`` OR on the
// connector definition; we only have the latter loosely typed on the
// connection object, so we fall back to a UI affordance driven by a
// probe request (handled in the right-pane effect).

interface CloudDrivePickerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /**
   * Called with the newly-created DataSource id once the ingest job is queued.
   * The parent is expected to refresh its list of documents.
   */
  onPicked?: (dataSourceId: string) => void
}

interface BreadcrumbFrame {
  id: string // path or parent id — whatever the adapter accepts
  name: string
}

const SLUG_ICONS: Record<string, React.ElementType> = {
  dropbox: HardDrive,
  "google-workspace": Cloud,
  onedrive: Cloud,
}

const SLUG_LABELS: Record<string, string> = {
  dropbox: "Dropbox",
  "google-workspace": "Google Drive",
  onedrive: "OneDrive",
}

export function CloudDrivePicker({
  open,
  onOpenChange,
  onPicked,
}: CloudDrivePickerProps) {
  const { data: connectionsResp, isLoading: connectionsLoading } = useConnections()
  const driveConnections = useMemo(
    () =>
      (connectionsResp?.items ?? []).filter((c) =>
        isCloudDriveSlug(c.connector_slug),
      ),
    [connectionsResp],
  )

  const [selected, setSelected] = useState<TenantConnection | null>(null)
  const [breadcrumb, setBreadcrumb] = useState<BreadcrumbFrame[]>([])

  const currentPath = breadcrumb.length
    ? breadcrumb[breadcrumb.length - 1].id
    : ""

  const listing = useDriveListing(
    selected?.id ?? null,
    currentPath,
  )

  const createMutation = useCreateDataSourceFromDrive()

  function resetAndClose() {
    setSelected(null)
    setBreadcrumb([])
    onOpenChange(false)
  }

  function handlePickConnection(conn: TenantConnection) {
    setSelected(conn)
    setBreadcrumb([])
  }

  function handleEnterFolder(item: DriveItem) {
    setBreadcrumb((bc) => [...bc, { id: item.id, name: item.name }])
  }

  function handleJumpBreadcrumb(index: number) {
    // -1 jumps back to root
    setBreadcrumb((bc) => bc.slice(0, index + 1))
  }

  async function handlePickFile(item: DriveItem) {
    if (!selected?.connector_slug || !selected?.id) return
    try {
      const result = await createMutation.mutateAsync({
        name: item.name,
        cloud_connection_id: selected.id,
        cloud_provider: selected.connector_slug,
        cloud_file_id: item.id,
        filename: item.name,
        mime_type: item.mime_type ?? undefined,
        file_size: item.size ?? undefined,
      })
      toast.success(`Ingesting ${item.name}…`, {
        description: "You'll see it in your documents once indexing finishes.",
      })
      onPicked?.(result.id)
      resetAndClose()
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to ingest file"
      toast.error(message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? onOpenChange(true) : resetAndClose())}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Ingest from cloud drive</DialogTitle>
          <DialogDescription>
            Pick a file from a connected cloud drive to add it to your RAG
            corpus. Supported providers: {CLOUD_DRIVE_SLUGS.map((s) => SLUG_LABELS[s]).join(", ")}.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-[220px_1fr] gap-4 min-h-[360px]">
          {/* Left: connection list */}
          <div className="border-r pr-3">
            <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">
              Connections
            </p>
            {connectionsLoading && <Spinner />}
            {!connectionsLoading && driveConnections.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No cloud-drive connections yet. Connect one from the{" "}
                <span className="font-medium">Settings → Connectors</span> page.
              </p>
            )}
            <ul className="flex flex-col gap-1">
              {driveConnections.map((conn) => {
                const Icon = SLUG_ICONS[conn.connector_slug ?? ""] ?? Cloud
                const isSel = conn.id === selected?.id
                return (
                  <li key={conn.id}>
                    <button
                      type="button"
                      onClick={() => handlePickConnection(conn)}
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors flex items-center gap-2",
                        isSel
                          ? "bg-accent text-accent-foreground"
                          : "hover:bg-accent/60",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate">
                        {conn.display_name}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>

          {/* Right: folder browser */}
          <div className="flex flex-col min-h-0">
            {!selected && (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Select a connection to browse its files.
              </div>
            )}
            {selected && (
              <>
                <Breadcrumb
                  connection={selected}
                  frames={breadcrumb}
                  onJump={handleJumpBreadcrumb}
                />
                <Separator className="my-2" />
                <ScrollArea className="flex-1">
                  {listing.isLoading && <Spinner />}
                  {listing.isError && (
                    <ErrorRow
                      message={
                        (listing.error as Error | undefined)?.message ??
                        "Failed to list files"
                      }
                    />
                  )}
                  {listing.data && listing.data.items.length === 0 && (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      This folder is empty.
                    </p>
                  )}
                  <ul className="divide-y">
                    {listing.data?.items.map((item) => (
                      <li key={item.id}>
                        <button
                          type="button"
                          disabled={createMutation.isPending}
                          onClick={() =>
                            item.is_folder
                              ? handleEnterFolder(item)
                              : handlePickFile(item)
                          }
                          className={cn(
                            "w-full px-2 py-2 text-left text-sm flex items-center gap-2",
                            "hover:bg-accent/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
                          )}
                        >
                          {item.is_folder ? (
                            <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                          ) : (
                            <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                          )}
                          <span className="flex-1 truncate">{item.name}</span>
                          {!item.is_folder && item.size !== null && (
                            <Badge variant="outline" className="text-xs">
                              {formatBytes(item.size)}
                            </Badge>
                          )}
                          {item.is_folder && (
                            <ChevronRight className="h-4 w-4 text-muted-foreground" />
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              </>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button variant="outline" onClick={resetAndClose}>
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Subcomponents ─────────────────────────────────────────

function Breadcrumb({
  connection,
  frames,
  onJump,
}: {
  connection: TenantConnection
  frames: BreadcrumbFrame[]
  onJump: (index: number) => void
}) {
  return (
    <nav className="flex flex-wrap items-center gap-1 text-sm">
      <button
        type="button"
        onClick={() => onJump(-1)}
        className="truncate rounded px-1 py-0.5 text-muted-foreground hover:bg-accent/50 hover:text-foreground"
      >
        {connection.display_name}
      </button>
      {frames.map((frame, index) => (
        <span key={frame.id} className="flex items-center gap-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
          <button
            type="button"
            onClick={() => onJump(index)}
            className="truncate rounded px-1 py-0.5 hover:bg-accent/50"
          >
            {frame.name}
          </button>
        </span>
      ))}
    </nav>
  )
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      Loading…
    </div>
  )
}

function ErrorRow({ message }: { message: string }) {
  return (
    <div className="rounded border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </div>
  )
}
