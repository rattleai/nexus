import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  Characteristic,
  CharacteristicCreate,
  CharacteristicUpdate,
  CharacteristicGroup,
  CharacteristicGroupCreate,
  CharacteristicGroupUpdate,
  CharacteristicValue,
  CharacteristicValueCreate,
  CharacteristicValueUpdate,
  CharacteristicAssignment,
  CharacteristicAssignmentCreate,
  CharacteristicAssignmentUpdate,
} from "@/apps/cpq/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── Characteristic Group Queries ────────────────────────

export function useCharacteristicGroups() {
  return useQuery({
    queryKey: queryKeys.characteristics.groups.list(),
    queryFn: async ({ signal }) =>
      api
        .get("characteristics/groups", { searchParams: { page_size: "100" }, signal })
        .json<PaginatedResponse<CharacteristicGroup>>(),
  })
}

export function useCreateCharacteristicGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: CharacteristicGroupCreate) =>
      api.post("characteristics/groups", { json: data }).json<CharacteristicGroup>(),
    onSuccess: (group) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.groups.all })
      toast.success(`Group "${group.name}" created`)
    },
  })
}

export function useUpdateCharacteristicGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: CharacteristicGroupUpdate }) =>
      api.put(`characteristics/groups/${id}`, { json: data }).json<CharacteristicGroup>(),
    onSuccess: (group) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.groups.all })
      toast.success(`Group "${group.name}" updated`)
    },
  })
}

export function useDeleteCharacteristicGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`characteristics/groups/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.groups.all })
      toast.success("Group deleted")
    },
  })
}

// ── Characteristic Queries ──────────────────────────────

export function useCharacteristics(filters?: { group_id?: string; char_type?: string }) {
  const params: Record<string, string> = { page_size: "200" }
  if (filters?.group_id) params.group_id = filters.group_id
  if (filters?.char_type) params.char_type = filters.char_type

  return useQuery({
    queryKey: queryKeys.characteristics.list(params),
    queryFn: async ({ signal }) =>
      api
        .get("characteristics", { searchParams: params, signal })
        .json<PaginatedResponse<Characteristic>>(),
  })
}

export function useCharacteristic(id: string | null) {
  return useQuery({
    queryKey: queryKeys.characteristics.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`characteristics/${id}`, { signal }).json<Characteristic>(),
    enabled: !!id,
  })
}

export function useCreateCharacteristic() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: CharacteristicCreate) =>
      api.post("characteristics", { json: data }).json<Characteristic>(),
    onSuccess: (char) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.all })
      toast.success(`Characteristic "${char.name}" created`)
    },
  })
}

export function useUpdateCharacteristic() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: CharacteristicUpdate }) =>
      api.put(`characteristics/${id}`, { json: data }).json<Characteristic>(),
    onSuccess: (char) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.all })
      toast.success(`Characteristic "${char.name}" updated`)
    },
  })
}

export function useDeleteCharacteristic() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`characteristics/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.all })
      toast.success("Characteristic deleted")
    },
  })
}

// ── Characteristic Value Mutations ──────────────────────

export function useAddCharacteristicValue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ charId, data }: { charId: string; data: CharacteristicValueCreate }) =>
      api
        .post(`characteristics/${charId}/values`, { json: data })
        .json<CharacteristicValue>(),
    onSuccess: (_value, { charId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.detail(charId) })
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.list() })
      toast.success("Value added")
    },
  })
}

export function useUpdateCharacteristicValue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      charId,
      valueId,
      data,
    }: {
      charId: string
      valueId: string
      data: CharacteristicValueUpdate
    }) =>
      api
        .put(`characteristics/${charId}/values/${valueId}`, { json: data })
        .json<CharacteristicValue>(),
    onSuccess: (_value, { charId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.detail(charId) })
      toast.success("Value updated")
    },
  })
}

export function useDeleteCharacteristicValue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ charId, valueId }: { charId: string; valueId: string }) => {
      await api.delete(`characteristics/${charId}/values/${valueId}`)
    },
    onSuccess: (_data, { charId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.detail(charId) })
      toast.success("Value deleted")
    },
  })
}

// ── Characteristic Assignment Mutations ─────────────────

export function useCharacteristicAssignments(productId: string | null) {
  return useQuery({
    queryKey: queryKeys.characteristics.assignments(productId ?? ""),
    queryFn: async ({ signal }) =>
      api
        .get("characteristics", {
          searchParams: { product_id: productId!, page_size: "200" },
          signal,
        })
        .json<PaginatedResponse<Characteristic>>(),
    enabled: !!productId,
  })
}

export function useAssignCharacteristic() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: CharacteristicAssignmentCreate) =>
      api.post("characteristics/assign", { json: data }).json<CharacteristicAssignment>(),
    onSuccess: (_assignment, data) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.assignments(data.product_id) })
      qc.invalidateQueries({ queryKey: queryKeys.products.detail(data.product_id) })
      toast.success("Characteristic assigned")
    },
  })
}

export function useRemoveAssignment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ assignmentId, productId }: { assignmentId: string; productId: string }) => {
      await api.delete(`characteristics/assign/${assignmentId}`)
      return productId
    },
    onSuccess: (productId) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.assignments(productId) })
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.assignmentsRaw(productId) })
      qc.invalidateQueries({ queryKey: queryKeys.products.detail(productId) })
      toast.success("Assignment removed")
    },
  })
}

export function useAssignmentsRaw(productId: string | null) {
  return useQuery({
    queryKey: queryKeys.characteristics.assignmentsRaw(productId ?? ""),
    queryFn: async ({ signal }) =>
      api
        .get("characteristics/assign", {
          searchParams: { product_id: productId! },
          signal,
        })
        .json<CharacteristicAssignment[]>(),
    enabled: !!productId,
  })
}

export function useUpdateAssignment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      assignmentId,
      data,
    }: {
      assignmentId: string
      productId: string
      data: CharacteristicAssignmentUpdate
    }) =>
      api
        .put(`characteristics/assign/${assignmentId}`, { json: data })
        .json<CharacteristicAssignment>(),
    onSuccess: (_assignment, { productId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.assignments(productId) })
      qc.invalidateQueries({ queryKey: queryKeys.characteristics.assignmentsRaw(productId) })
      qc.invalidateQueries({ queryKey: queryKeys.products.detail(productId) })
      toast.success("Assignment updated")
    },
  })
}
