import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { HTTPError } from "ky"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { CursorPaginatedResponse, FileRecord } from "@/types/api"

export function useFiles() {
  return useQuery({
    queryKey: queryKeys.files.list(),
    queryFn: ({ signal }) =>
      api.get("files", { signal }).json<CursorPaginatedResponse<FileRecord>>(),
    retry: (count, err) =>
      !(err instanceof HTTPError && err.response.status === 404) && count < 2,
  })
}

export function useUploadFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData()
      formData.append("file", file)
      return api.post("files", { body: formData }).json<FileRecord>()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.files.all }),
  })
}

export function useDeleteFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`files/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.files.all }),
  })
}
