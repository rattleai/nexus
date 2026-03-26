import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  BOMHeader,
  BOMHeaderCreate,
  BOMHeaderUpdate,
  BOMHeaderDetail,
  BOMItem,
  BOMItemCreate,
  BOMItemUpdate,
  WhereUsedResult,
} from "@/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── BOM Header Queries ──────────────────────────────────

export function useBOMs(productId?: string) {
  const params: Record<string, string> = { page_size: "50" }
  if (productId) params.product_id = productId

  return useQuery({
    queryKey: queryKeys.boms.list(productId),
    queryFn: async ({ signal }) =>
      api
        .get("boms", { searchParams: params, signal })
        .json<PaginatedResponse<BOMHeader>>(),
  })
}

export function useBOM(id: string | null) {
  return useQuery({
    queryKey: queryKeys.boms.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`boms/${id}`, { signal }).json<BOMHeaderDetail>(),
    enabled: !!id,
  })
}

export function useCreateBOM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: BOMHeaderCreate) =>
      api.post("boms", { json: data }).json<BOMHeader>(),
    onSuccess: (bom) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.all })
      toast.success(`BOM "${bom.name}" created`)
    },
  })
}

export function useUpdateBOM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: BOMHeaderUpdate }) =>
      api.put(`boms/${id}`, { json: data }).json<BOMHeader>(),
    onSuccess: (bom) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.all })
      qc.invalidateQueries({ queryKey: queryKeys.boms.detail(bom.id) })
      toast.success(`BOM "${bom.name}" updated`)
    },
  })
}

export function useDeleteBOM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`boms/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.all })
      toast.success("BOM deleted")
    },
  })
}

// ── BOM Item Mutations ──────────────────────────────────

export function useCreateBOMItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ bomId, data }: { bomId: string; data: BOMItemCreate }) =>
      api.post(`boms/${bomId}/items`, { json: data }).json<BOMItem>(),
    onSuccess: (_item, { bomId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.detail(bomId) })
      toast.success("Item added")
    },
  })
}

export function useUpdateBOMItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      bomId,
      itemId,
      data,
    }: {
      bomId: string
      itemId: string
      data: BOMItemUpdate
    }) => api.put(`boms/${bomId}/items/${itemId}`, { json: data }).json<BOMItem>(),
    onSuccess: (_item, { bomId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.detail(bomId) })
      toast.success("Item updated")
    },
  })
}

export function useDeleteBOMItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ bomId, itemId }: { bomId: string; itemId: string }) => {
      await api.delete(`boms/${bomId}/items/${itemId}`)
    },
    onSuccess: (_data, { bomId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.detail(bomId) })
      toast.success("Item deleted")
    },
  })
}

export function useReorderBOMItems() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ bomId, itemIds }: { bomId: string; itemIds: string[] }) =>
      api.post(`boms/${bomId}/items/reorder`, { json: { item_ids: itemIds } }).json(),
    onSuccess: (_data, { bomId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.boms.detail(bomId) })
    },
  })
}

// ── Where-Used Query ────────────────────────────────────

export function useWhereUsed(partNumber: string | null) {
  return useQuery({
    queryKey: queryKeys.boms.whereUsed(partNumber ?? ""),
    queryFn: async ({ signal }) =>
      api
        .get(`boms/items/where-used/${partNumber}`, { signal })
        .json<WhereUsedResult[]>(),
    enabled: !!partNumber,
  })
}
