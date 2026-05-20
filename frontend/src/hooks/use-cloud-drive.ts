import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"

// ── Types ───────────────────────────────────────────────

export interface DriveItem {
  id: string
  name: string
  path: string
  is_folder: boolean
  size: number | null
  mime_type: string | null
  modified_at: string | null
  extra: Record<string, unknown>
}

export interface DriveListing {
  items: DriveItem[]
  cursor: string | null
}

export interface DataSourceFromDriveBody {
  name: string
  cloud_connection_id: string
  cloud_provider: string
  cloud_file_id: string
  filename?: string
  mime_type?: string
  file_size?: number
}

// Connector slugs that resolve to a cloud-drive adapter on the backend.
// Keep in sync with ``supported_drive_slugs()`` in app/connectors/drive/base.py.
export const CLOUD_DRIVE_SLUGS = ["dropbox", "google-workspace", "onedrive"] as const
export type CloudDriveSlug = (typeof CLOUD_DRIVE_SLUGS)[number]

export function isCloudDriveSlug(slug: string | null | undefined): slug is CloudDriveSlug {
  return !!slug && (CLOUD_DRIVE_SLUGS as readonly string[]).includes(slug)
}

// ── Queries ─────────────────────────────────────────────

export function useDriveListing(
  connectionId: string | null,
  path: string,
  cursor: string | null = null,
) {
  return useQuery({
    queryKey: queryKeys.cloudDrive.listing(connectionId ?? "", path, cursor),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams()
      params.set("connection_id", connectionId!)
      if (path) params.set("path", path)
      if (cursor) params.set("cursor", cursor)
      return api.get(`datasources/browse?${params.toString()}`, { signal }).json<DriveListing>()
    },
    enabled: !!connectionId,
  })
}

// ── Mutations ───────────────────────────────────────────

export function useCreateDataSourceFromDrive() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DataSourceFromDriveBody) =>
      api
        .post("datasources", {
          json: {
            name: body.name,
            source_type: "cloud_drive",
            cloud_connection_id: body.cloud_connection_id,
            cloud_provider: body.cloud_provider,
            cloud_file_id: body.cloud_file_id,
            filename: body.filename,
            mime_type: body.mime_type,
            file_size: body.file_size,
          },
        })
        .json<{ id: string }>(),
    onSuccess: () => {
      // Datasource lists live under a different key factory (cpq); the
      // RAG panel refetches on mount, so invalidating the cloud-drive
      // listing keeps the picker tree fresh between pick actions.
      qc.invalidateQueries({ queryKey: queryKeys.cloudDrive.all })
    },
  })
}
