import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  Product,
  ProductCreate,
  ProductUpdate,
  ProductFamily,
  ProductFamilyCreate,
  ProductFamilyUpdate,
  ProductVersion,
  ProductVersionCreate,
} from "@/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── Product Family Queries ──────────────────────────────

export function useProductFamilies() {
  return useQuery({
    queryKey: queryKeys.productFamilies.list(),
    queryFn: async ({ signal }) =>
      api
        .get("products/families", { searchParams: { page_size: "100" }, signal })
        .json<PaginatedResponse<ProductFamily>>(),
  })
}

export function useProductFamily(id: string | null) {
  return useQuery({
    queryKey: queryKeys.productFamilies.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`products/families/${id}`, { signal }).json<ProductFamily>(),
    enabled: !!id,
  })
}

export function useCreateProductFamily() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ProductFamilyCreate) =>
      api.post("products/families", { json: data }).json<ProductFamily>(),
    onSuccess: (family) => {
      qc.invalidateQueries({ queryKey: queryKeys.productFamilies.all })
      toast.success(`Family "${family.name}" created`)
    },
  })
}

export function useUpdateProductFamily() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: ProductFamilyUpdate }) =>
      api.put(`products/families/${id}`, { json: data }).json<ProductFamily>(),
    onSuccess: (family) => {
      qc.invalidateQueries({ queryKey: queryKeys.productFamilies.all })
      toast.success(`Family "${family.name}" updated`)
    },
  })
}

export function useDeleteProductFamily() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`products/families/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.productFamilies.all })
      toast.success("Family deleted")
    },
  })
}

// ── Product Queries ─────────────────────────────────────

export function useProducts(filters?: { family_id?: string; status?: string }) {
  const params: Record<string, string> = { page_size: "100" }
  if (filters?.family_id) params.family_id = filters.family_id
  if (filters?.status && filters.status !== "all") params.status = filters.status

  return useQuery({
    queryKey: queryKeys.products.list(params),
    queryFn: async ({ signal }) =>
      api
        .get("products", { searchParams: params, signal })
        .json<PaginatedResponse<Product>>(),
  })
}

export function useProduct(id: string | null) {
  return useQuery({
    queryKey: queryKeys.products.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`products/${id}`, { signal }).json<Product>(),
    enabled: !!id,
  })
}

export function useCreateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ProductCreate) =>
      api.post("products", { json: data }).json<Product>(),
    onSuccess: (product) => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
      toast.success(`Product "${product.name}" created`)
    },
  })
}

export function useUpdateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: ProductUpdate }) =>
      api.put(`products/${id}`, { json: data }).json<Product>(),
    onSuccess: (product) => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
      qc.invalidateQueries({ queryKey: queryKeys.products.detail(product.id) })
      toast.success(`Product "${product.name}" updated`)
    },
  })
}

export function useDeleteProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`products/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
      toast.success("Product deleted")
    },
  })
}

// ── Product Version Queries ─────────────────────────────

export function useProductVersions(productId: string | null) {
  return useQuery({
    queryKey: queryKeys.products.versions(productId ?? ""),
    queryFn: async ({ signal }) =>
      api
        .get(`products/${productId}/versions`, { searchParams: { page_size: "50" }, signal })
        .json<PaginatedResponse<ProductVersion>>(),
    enabled: !!productId,
  })
}

export function usePublishVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ productId, data }: { productId: string; data?: ProductVersionCreate }) =>
      api.post(`products/${productId}/versions`, { json: data ?? {} }).json<ProductVersion>(),
    onSuccess: (_version, { productId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.products.versions(productId) })
      qc.invalidateQueries({ queryKey: queryKeys.products.detail(productId) })
      toast.success("Version published")
    },
  })
}

export function useActivateVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ productId, versionId }: { productId: string; versionId: string }) =>
      api
        .post(`products/${productId}/versions/${versionId}/activate`)
        .json<ProductVersion>(),
    onSuccess: (_version, { productId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.products.versions(productId) })
      toast.success("Version activated")
    },
  })
}

export function useRecompileVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ productId, versionId }: { productId: string; versionId: string }) =>
      api
        .post(`products/${productId}/versions/${versionId}/recompile`)
        .json<ProductVersion>(),
    onSuccess: (_version, { productId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.products.versions(productId) })
      toast.success("Snapshot recompiled")
    },
  })
}
