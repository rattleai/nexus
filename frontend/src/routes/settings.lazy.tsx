import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { CheckCircle2, AlertCircle, Download, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { PageHeader } from "@/components/page-header"
import { useAuthContext } from "@/lib/auth-context"
import { useAuth } from "@/hooks/use-auth"
import { useHealth } from "@/hooks/use-health"
import { useExportTenantData, useExportAccountData, useDeleteAccount } from "@/hooks/use-usage"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/settings")({
  component: SettingsPage,
})

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(/[a-z]/, "Must contain a lowercase letter")
      .regex(/[A-Z]/, "Must contain an uppercase letter")
      .regex(/[0-9]/, "Must contain a digit"),
    confirm_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  })

type PasswordValues = z.infer<typeof passwordSchema>

function SettingsPage() {
  return (
    <AuthGuard>
      <div className="space-y-6">
        <PageHeader title="Settings" description="Manage your account and preferences." />
        <Tabs defaultValue="profile">
          <TabsList>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="security">Security</TabsTrigger>
            <TabsTrigger value="data">Data</TabsTrigger>
            <TabsTrigger value="danger">Danger Zone</TabsTrigger>
          </TabsList>
          <TabsContent value="profile" className="mt-6">
            <ProfileTab />
          </TabsContent>
          <TabsContent value="security" className="mt-6">
            <SecurityTab />
          </TabsContent>
          <TabsContent value="data" className="mt-6">
            <DataTab />
          </TabsContent>
          <TabsContent value="danger" className="mt-6">
            <DangerTab />
          </TabsContent>
        </Tabs>
      </div>
    </AuthGuard>
  )
}

function ProfileTab() {
  const { user } = useAuthContext()
  const { data: health } = useHealth()
  const { apiKey, clearApiKey } = useAuth()
  const [displayName, setDisplayName] = useState(user?.display_name ?? "")
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch("auth/me", { json: { display_name: displayName } })
      toast.success("Profile updated")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    } finally {
      setSaving(false)
    }
  }

  const handleResendVerification = async () => {
    try {
      await api.post("auth/resend-verification")
      toast.success("Verification email sent")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="display-name">Display Name</Label>
            <Input
              id="display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Email</Label>
            <div className="flex items-center gap-2">
              <Input value={user?.email ?? ""} disabled />
              {user?.email_verified ? (
                <Badge variant="default" className="gap-1 shrink-0">
                  <CheckCircle2 className="h-3 w-3" />
                  Verified
                </Badge>
              ) : (
                <Badge variant="secondary" className="gap-1 shrink-0">
                  <AlertCircle className="h-3 w-3" />
                  Unverified
                </Badge>
              )}
            </div>
            {user && !user.email_verified && (
              <Button variant="link" size="sm" className="p-0 h-auto" onClick={handleResendVerification}>
                Resend verification email
              </Button>
            )}
          </div>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Platform Info</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-muted-foreground">Version</dt>
              <dd className="font-medium">{health?.version ?? "\u2014"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Status</dt>
              <dd className="font-medium capitalize">{health?.status ?? "\u2014"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {apiKey && (
        <Card>
          <CardHeader>
            <CardTitle>API Key Authentication</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-sm text-muted-foreground mb-1">Current API Key</p>
              <code className="text-sm font-mono">
                {apiKey.slice(0, 8)}{"*".repeat(24)}
              </code>
            </div>
            <Button variant="outline" onClick={clearApiKey}>
              Disconnect
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function SecurityTab() {
  const form = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm_password: "" },
  })

  const onSubmit = async (data: PasswordValues) => {
    try {
      await api.post("auth/change-password", {
        json: { current_password: data.current_password, new_password: data.new_password },
      })
      toast.success("Password changed")
      form.reset()
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change Password</CardTitle>
        <CardDescription>Update your password to keep your account secure.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 max-w-md">
          <div className="space-y-2">
            <Label htmlFor="current_password">Current Password</Label>
            <Input id="current_password" type="password" {...form.register("current_password")} />
            {form.formState.errors.current_password && (
              <p className="text-xs text-destructive">{form.formState.errors.current_password.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_password">New Password</Label>
            <Input id="new_password" type="password" {...form.register("new_password")} />
            {form.formState.errors.new_password && (
              <p className="text-xs text-destructive">{form.formState.errors.new_password.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm_password">Confirm New Password</Label>
            <Input id="confirm_password" type="password" {...form.register("confirm_password")} />
            {form.formState.errors.confirm_password && (
              <p className="text-xs text-destructive">{form.formState.errors.confirm_password.message}</p>
            )}
          </div>
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? "Changing..." : "Change Password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function DataTab() {
  const exportTenant = useExportTenantData()
  const exportAccount = useExportAccountData()
  const [format, setFormat] = useState<"json" | "csv">("json")

  const handleExport = async (type: "tenant" | "account") => {
    try {
      const mutation = type === "tenant" ? exportTenant : exportAccount
      await mutation.mutateAsync({ format })
      toast.success("Export started. You'll receive a notification when it's ready.")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data Export</CardTitle>
        <CardDescription>Export your data in JSON or CSV format.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Export Format</Label>
          <Select value={format} onValueChange={(v) => setFormat(v as "json" | "csv")}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="json">JSON</SelectItem>
              <SelectItem value="csv">CSV</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Separator />
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => handleExport("tenant")}
            disabled={exportTenant.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            Export Workspace Data
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport("account")}
            disabled={exportAccount.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            Export Personal Data
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DangerTab() {
  const deleteAccount = useDeleteAccount()

  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">Danger Zone</CardTitle>
        <CardDescription>
          Irreversible actions. Please be certain before proceeding.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm text-muted-foreground">
            Deleting your account will remove all your data after a 30-day grace period.
            During this time you can contact support to recover your account.
          </p>
        </div>
        <ConfirmDialog
          title="Delete Account"
          description="This will permanently delete your account and all associated data after a 30-day grace period. This action cannot be undone."
          variant="destructive"
          confirmLabel="Delete Account"
          onConfirm={async () => {
            try {
              await deleteAccount.mutateAsync()
              toast.success("Account deletion scheduled")
            } catch (err) {
              const e = await parseApiError(err)
              toast.error(e.detail)
            }
          }}
        >
          <Button variant="destructive">
            <Trash2 className="mr-2 h-4 w-4" />
            Delete Account
          </Button>
        </ConfirmDialog>
      </CardContent>
    </Card>
  )
}
