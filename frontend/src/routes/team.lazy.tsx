import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Users, Plus, Mail, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { LoadingState } from "@/components/loading-state"
import {
  useTeamMembers,
  useInvitations,
  useInviteMember,
  useUpdateMemberRole,
  useRemoveMember,
  useRevokeInvitation,
} from "@/hooks/use-team"
import { parseApiError } from "@/lib/api-client"
import { formatDate } from "@/lib/format"
import type { TeamMember, TeamRole, Invitation } from "@/types/api"

export const Route = createLazyFileRoute("/team")({
  component: TeamPage,
})

const roleVariant: Record<TeamRole, "default" | "secondary" | "outline"> = {
  owner: "default",
  admin: "default",
  member: "secondary",
  viewer: "outline",
}

function MemberActions({ member }: { member: TeamMember }) {
  const updateRole = useUpdateMemberRole()
  const removeMember = useRemoveMember()

  if (member.role === "owner") return null

  return (
    <div className="flex items-center gap-2">
      <Select
        value={member.role}
        onValueChange={async (role: string) => {
          try {
            await updateRole.mutateAsync({ id: member.id, role: role as TeamRole })
            toast.success("Role updated")
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <SelectTrigger className="w-28 h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="admin">Admin</SelectItem>
          <SelectItem value="member">Member</SelectItem>
          <SelectItem value="viewer">Viewer</SelectItem>
        </SelectContent>
      </Select>
      <ConfirmDialog
        title="Remove Member"
        description={`Remove ${member.display_name || member.email} from the team? They will lose access immediately.`}
        variant="destructive"
        confirmLabel="Remove"
        onConfirm={async () => {
          try {
            await removeMember.mutateAsync(member.id)
            toast.success("Member removed")
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <Button variant="ghost" size="sm">
          Remove
        </Button>
      </ConfirmDialog>
    </div>
  )
}

const columns: ColumnDef<TeamMember>[] = [
  {
    accessorKey: "display_name",
    header: "Name",
    cell: ({ row }) => (
      <div>
        <p className="font-medium">{row.original.display_name || row.original.email}</p>
        {row.original.display_name && (
          <p className="text-xs text-muted-foreground">{row.original.email}</p>
        )}
      </div>
    ),
  },
  { accessorKey: "email", header: "Email" },
  {
    accessorKey: "role",
    header: "Role",
    cell: ({ row }) => (
      <Badge variant={roleVariant[row.original.role]}>{row.original.role}</Badge>
    ),
  },
  {
    accessorKey: "joined_at",
    header: "Joined",
    cell: ({ row }) => formatDate(row.original.joined_at),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <MemberActions member={row.original} />,
  },
]

function InvitationRow({ invitation }: { invitation: Invitation }) {
  const revokeInvitation = useRevokeInvitation()

  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex items-center gap-3">
        <Mail className="h-4 w-4 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">{invitation.email}</p>
          <p className="text-xs text-muted-foreground">
            Role: {invitation.role} &middot; Expires {formatDate(invitation.expires_at)}
          </p>
        </div>
      </div>
      <ConfirmDialog
        title="Revoke Invitation"
        description={`Revoke the invitation sent to ${invitation.email}?`}
        variant="destructive"
        confirmLabel="Revoke"
        onConfirm={async () => {
          try {
            await revokeInvitation.mutateAsync(invitation.id)
            toast.success("Invitation revoked")
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <Button variant="ghost" size="sm">
          <X className="h-4 w-4" />
        </Button>
      </ConfirmDialog>
    </div>
  )
}

function TeamPage() {
  const membersQuery = useTeamMembers()
  const { data: invitations, isLoading: invitationsLoading } = useInvitations()
  const inviteMember = useInviteMember()
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState<TeamRole>("member")

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return
    try {
      await inviteMember.mutateAsync({ email: inviteEmail.trim(), role: inviteRole })
      toast.success("Invitation sent")
      setInviteOpen(false)
      setInviteEmail("")
      setInviteRole("member")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  // Cast query to match ResourcePage's expected shape
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const queryResult = membersQuery as any

  return (
    <AuthGuard requiredRole="admin">
      <ResourcePage
        title="Team"
        description="Manage your team members and invitations."
        queryResult={queryResult}
        columns={columns}
        searchKey="email"
        searchPlaceholder="Search members..."
        emptyState={{
          icon: Users,
          title: "No team members",
          description: "Invite someone to join your team.",
          action: (
            <Button onClick={() => setInviteOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Invite Member
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setInviteOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Invite Member
          </Button>
        }
      />

      {/* Pending Invitations */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Pending Invitations</CardTitle>
          <CardDescription>Invitations that haven't been accepted yet.</CardDescription>
        </CardHeader>
        <CardContent>
          {invitationsLoading ? (
            <LoadingState variant="skeleton" rows={2} />
          ) : !invitations || invitations.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending invitations.</p>
          ) : (
            <div className="divide-y">
              {invitations.map((inv) => (
                <InvitationRow key={inv.id} invitation={inv} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Invite Dialog */}
      <FormDialog
        open={inviteOpen}
        onOpenChange={(open) => {
          setInviteOpen(open)
          if (!open) {
            setInviteEmail("")
            setInviteRole("member")
          }
        }}
        title="Invite Team Member"
        description="Send an email invitation to join your team."
        isPending={inviteMember.isPending}
        onSubmit={handleInvite}
        submitLabel="Send Invitation"
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-email">Email address</Label>
            <Input
              id="invite-email"
              type="email"
              placeholder="colleague@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-role">Role</Label>
            <Select value={inviteRole} onValueChange={(v) => setInviteRole(v as TeamRole)}>
              <SelectTrigger id="invite-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">Admin</SelectItem>
                <SelectItem value="member">Member</SelectItem>
                <SelectItem value="viewer">Viewer</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </FormDialog>
    </AuthGuard>
  )
}
