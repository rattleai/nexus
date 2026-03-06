import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { Invitation, TeamMember, TeamRole } from "@/types/api"

export function useTeamMembers() {
  return useQuery({
    queryKey: queryKeys.team.members(),
    queryFn: ({ signal }) =>
      api.get("team/members", { signal }).json<TeamMember[]>(),
  })
}

export function useInvitations() {
  return useQuery({
    queryKey: queryKeys.team.invitations(),
    queryFn: ({ signal }) =>
      api.get("team/invitations", { signal }).json<Invitation[]>(),
  })
}

export function useInviteMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; role: TeamRole }) =>
      api.post("team/invite", { json: body }).json<Invitation>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.team.all }),
  })
}

export function useUpdateMemberRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, role }: { id: string; role: TeamRole }) =>
      api.patch(`team/members/${id}`, { json: { role } }).json<TeamMember>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.team.all }),
  })
}

export function useRemoveMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`team/members/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.team.all }),
  })
}

export function useRevokeInvitation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`team/invitations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.team.all }),
  })
}
