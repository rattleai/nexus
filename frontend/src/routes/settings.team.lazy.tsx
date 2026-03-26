import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
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

export const Route = createLazyFileRoute("/settings/team")({
  component: SettingsTeamPage,
})

const roleVariant: Record<TeamRole, "default" | "secondary" | "outline"> = {
  owner: "default",
  admin: "default",
  member: "secondary",
  viewer: "outline",
}

function MemberActions({ member }: { member: TeamMember }) {
  const { t } = useTranslation("team")
  const { t: tc } = useTranslation("common")
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
            toast.success(t("role_updated"))
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
          <SelectItem value="admin">{t("roles.admin")}</SelectItem>
          <SelectItem value="member">{t("roles.member")}</SelectItem>
          <SelectItem value="viewer">{t("roles.viewer")}</SelectItem>
        </SelectContent>
      </Select>
      <ConfirmDialog
        title={t("remove_title")}
        description={t("remove_desc", { name: member.display_name || member.email })}
        variant="destructive"
        confirmLabel={tc("buttons.remove")}
        onConfirm={async () => {
          try {
            await removeMember.mutateAsync(member.id)
            toast.success(t("remove_success"))
          } catch (err) {
            const e = await parseApiError(err)
            toast.error(e.detail)
          }
        }}
      >
        <Button variant="ghost" size="sm">
          {tc("buttons.remove")}
        </Button>
      </ConfirmDialog>
    </div>
  )
}

function useTeamColumns(): ColumnDef<TeamMember>[] {
  const { t } = useTranslation("team")
  const { t: tc } = useTranslation("common")

  return [
    {
      accessorKey: "display_name",
      header: t("table.name"),
      cell: ({ row }) => (
        <div>
          <p className="font-medium">{row.original.display_name || row.original.email}</p>
          {row.original.display_name && (
            <p className="text-xs text-muted-foreground">{row.original.email}</p>
          )}
        </div>
      ),
    },
    { accessorKey: "email", header: t("table.email") },
    {
      accessorKey: "role",
      header: t("table.role"),
      cell: ({ row }) => (
        <Badge variant={roleVariant[row.original.role]}>{row.original.role}</Badge>
      ),
    },
    {
      accessorKey: "joined_at",
      header: t("table.joined"),
      cell: ({ row }) => formatDate(row.original.joined_at),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{tc("labels.actions")}</span>,
      cell: ({ row }) => <MemberActions member={row.original} />,
    },
  ]
}

function InvitationRow({ invitation }: { invitation: Invitation }) {
  const { t } = useTranslation("team")
  const { t: tc } = useTranslation("common")
  const revokeInvitation = useRevokeInvitation()

  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex items-center gap-3">
        <Mail className="h-4 w-4 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">{invitation.email}</p>
          <p className="text-xs text-muted-foreground">
            {t("table.role")}: {invitation.role} &middot; {t("expires")} {formatDate(invitation.expires_at)}
          </p>
        </div>
      </div>
      <ConfirmDialog
        title={t("revoke_invitation_title")}
        description={t("revoke_invitation_desc", { email: invitation.email })}
        variant="destructive"
        confirmLabel={tc("buttons.revoke")}
        onConfirm={async () => {
          try {
            await revokeInvitation.mutateAsync(invitation.id)
            toast.success(t("revoke_success"))
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

function SettingsTeamPage() {
  return (
    <AuthGuard requiredRole="admin">
      <TeamContent />
    </AuthGuard>
  )
}

function TeamContent() {
  const { t } = useTranslation("team")
  const membersQuery = useTeamMembers()
  const { data: invitations, isLoading: invitationsLoading } = useInvitations()
  const inviteMember = useInviteMember()
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState<TeamRole>("member")
  const columns = useTeamColumns()

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return
    try {
      await inviteMember.mutateAsync({ email: inviteEmail.trim(), role: inviteRole })
      toast.success(t("invite_success"))
      setInviteOpen(false)
      setInviteEmail("")
      setInviteRole("member")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const queryResult = membersQuery as any

  return (
    <>
      <ResourcePage
        title={t("title")}
        description={t("description")}
        queryResult={queryResult}
        columns={columns}
        searchKey="email"
        searchPlaceholder={t("search_placeholder")}
        emptyState={{
          icon: Users,
          title: t("no_members"),
          description: t("no_members_desc"),
          action: (
            <Button onClick={() => setInviteOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("invite_member")}
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setInviteOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t("invite_member")}
          </Button>
        }
      />
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t("pending_invitations")}</CardTitle>
          <CardDescription>{t("pending_invitations_desc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {invitationsLoading ? (
            <LoadingState variant="skeleton" rows={2} />
          ) : !invitations || invitations.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("no_pending_invitations")}</p>
          ) : (
            <div className="divide-y">
              {invitations.map((inv) => (
                <InvitationRow key={inv.id} invitation={inv} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      <FormDialog
        open={inviteOpen}
        onOpenChange={(open) => {
          setInviteOpen(open)
          if (!open) { setInviteEmail(""); setInviteRole("member") }
        }}
        title={t("invite_dialog_title")}
        description={t("invite_dialog_desc")}
        isPending={inviteMember.isPending}
        onSubmit={handleInvite}
        submitLabel={t("send_invitation")}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-email">{t("invite_email_label")}</Label>
            <Input
              id="invite-email"
              type="email"
              placeholder={t("invite_email_placeholder")}
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-role">{t("invite_role_label")}</Label>
            <Select value={inviteRole} onValueChange={(v) => setInviteRole(v as TeamRole)}>
              <SelectTrigger id="invite-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">{t("roles.admin")}</SelectItem>
                <SelectItem value="member">{t("roles.member")}</SelectItem>
                <SelectItem value="viewer">{t("roles.viewer")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </FormDialog>
    </>
  )
}
