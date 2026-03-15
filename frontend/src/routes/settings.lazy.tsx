import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
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
import { supportedLanguages } from "@/lib/i18n"

export const Route = createLazyFileRoute("/settings")({
  component: SettingsPage,
})

function SettingsPage() {
  const { t } = useTranslation("settings")

  return (
    <AuthGuard>
      <div className="space-y-6">
        <PageHeader title={t("title")} description={t("description")} />
        <Tabs defaultValue="profile">
          <TabsList>
            <TabsTrigger value="profile">{t("tabs.profile")}</TabsTrigger>
            <TabsTrigger value="language">{t("tabs.language")}</TabsTrigger>
            <TabsTrigger value="security">{t("tabs.security")}</TabsTrigger>
            <TabsTrigger value="data">{t("tabs.data")}</TabsTrigger>
            <TabsTrigger value="danger">{t("tabs.danger")}</TabsTrigger>
          </TabsList>
          <TabsContent value="profile" className="mt-6">
            <ProfileTab />
          </TabsContent>
          <TabsContent value="language" className="mt-6">
            <LanguageTab />
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
  const { t } = useTranslation("settings")
  const { t: tc } = useTranslation("common")

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch("auth/me", { json: { display_name: displayName } })
      toast.success(t("profile.save_success"))
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
      toast.success(t("profile.verification_sent"))
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("profile.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="display-name">{t("profile.display_name")}</Label>
            <Input
              id="display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>{t("profile.email")}</Label>
            <div className="flex items-center gap-2">
              <Input value={user?.email ?? ""} disabled />
              {user?.email_verified ? (
                <Badge variant="default" className="gap-1 shrink-0">
                  <CheckCircle2 className="h-3 w-3" />
                  {tc("status.verified")}
                </Badge>
              ) : (
                <Badge variant="secondary" className="gap-1 shrink-0">
                  <AlertCircle className="h-3 w-3" />
                  {tc("status.unverified")}
                </Badge>
              )}
            </div>
            {user && !user.email_verified && (
              <Button variant="link" size="sm" className="p-0 h-auto" onClick={handleResendVerification}>
                {t("profile.resend_verification")}
              </Button>
            )}
          </div>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? tc("buttons.saving") : tc("buttons.save_changes")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("platform_info.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-muted-foreground">{t("platform_info.version")}</dt>
              <dd className="font-medium">{health?.version ?? "\u2014"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("platform_info.status")}</dt>
              <dd className="font-medium capitalize">{health?.status ?? "\u2014"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {apiKey && (
        <Card>
          <CardHeader>
            <CardTitle>{t("api_key_auth.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-sm text-muted-foreground mb-1">{t("api_key_auth.current_key")}</p>
              <code className="text-sm font-mono">
                {apiKey.slice(0, 8)}{"*".repeat(24)}
              </code>
            </div>
            <Button variant="outline" onClick={clearApiKey}>
              {t("api_key_auth.disconnect")}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function LanguageTab() {
  const { i18n, t } = useTranslation("settings")
  const { t: tc } = useTranslation("common")
  const { isAuthenticated } = useAuthContext()
  const [selectedLang, setSelectedLang] = useState(i18n.language)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await i18n.changeLanguage(selectedLang)

      if (isAuthenticated) {
        await api.patch("auth/me", { json: { locale: selectedLang } })
      }
      toast.success(t("language.save_success"))
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("language.title")}</CardTitle>
        <CardDescription>{t("language.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>{t("language.select_label")}</Label>
          <Select value={selectedLang} onValueChange={setSelectedLang}>
            <SelectTrigger className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {supportedLanguages.map((lang) => (
                <SelectItem key={lang.code} value={lang.code}>
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{lang.nativeName}</span>
                    {lang.nativeName !== lang.name && (
                      <span className="text-muted-foreground text-xs">({lang.name})</span>
                    )}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={handleSave} disabled={saving || selectedLang === i18n.language}>
          {saving ? tc("buttons.saving") : tc("buttons.save_changes")}
        </Button>
      </CardContent>
    </Card>
  )
}

function SecurityTab() {
  const { t } = useTranslation("settings")
  const { t: tv } = useTranslation("validation")

  const passwordSchema = z
    .object({
      current_password: z.string().min(1, tv("current_password_required")),
      new_password: z
        .string()
        .min(8, tv("password_min_length", { count: 8 }))
        .regex(/[a-z]/, tv("password_lowercase"))
        .regex(/[A-Z]/, tv("password_uppercase"))
        .regex(/[0-9]/, tv("password_digit")),
      confirm_password: z.string(),
    })
    .refine((data) => data.new_password === data.confirm_password, {
      message: tv("passwords_not_match"),
      path: ["confirm_password"],
    })

  type PasswordValues = z.infer<typeof passwordSchema>

  const form = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm_password: "" },
  })

  const onSubmit = async (data: PasswordValues) => {
    try {
      await api.post("auth/change-password", {
        json: { current_password: data.current_password, new_password: data.new_password },
      })
      toast.success(t("security.success"))
      form.reset()
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("security.title")}</CardTitle>
        <CardDescription>{t("security.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 max-w-md">
          <div className="space-y-2">
            <Label htmlFor="current_password">{t("security.current_password")}</Label>
            <Input id="current_password" type="password" {...form.register("current_password")} />
            {form.formState.errors.current_password && (
              <p className="text-xs text-destructive">{form.formState.errors.current_password.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_password">{t("security.new_password")}</Label>
            <Input id="new_password" type="password" {...form.register("new_password")} />
            {form.formState.errors.new_password && (
              <p className="text-xs text-destructive">{form.formState.errors.new_password.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm_password">{t("security.confirm_password")}</Label>
            <Input id="confirm_password" type="password" {...form.register("confirm_password")} />
            {form.formState.errors.confirm_password && (
              <p className="text-xs text-destructive">{form.formState.errors.confirm_password.message}</p>
            )}
          </div>
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? t("security.submitting") : t("security.submit")}
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
  const { t } = useTranslation("settings")

  const handleExport = async (type: "tenant" | "account") => {
    try {
      const mutation = type === "tenant" ? exportTenant : exportAccount
      await mutation.mutateAsync({ format })
      toast.success(t("data.export_success"))
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("data.title")}</CardTitle>
        <CardDescription>{t("data.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>{t("data.format_label")}</Label>
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
            {t("data.export_workspace")}
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport("account")}
            disabled={exportAccount.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            {t("data.export_personal")}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DangerTab() {
  const deleteAccount = useDeleteAccount()
  const { t } = useTranslation("settings")

  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">{t("danger.title")}</CardTitle>
        <CardDescription>
          {t("danger.description")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {t("danger.delete_info")}
          </p>
        </div>
        <ConfirmDialog
          title={t("danger.delete_title")}
          description={t("danger.delete_description")}
          variant="destructive"
          confirmLabel={t("danger.delete_confirm")}
          onConfirm={async () => {
            try {
              await deleteAccount.mutateAsync()
              toast.success(t("danger.delete_success"))
            } catch (err) {
              const e = await parseApiError(err)
              toast.error(e.detail)
            }
          }}
        >
          <Button variant="destructive">
            <Trash2 className="mr-2 h-4 w-4" />
            {t("danger.delete_confirm")}
          </Button>
        </ConfirmDialog>
      </CardContent>
    </Card>
  )
}
