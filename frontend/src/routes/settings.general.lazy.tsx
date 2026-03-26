import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { CheckCircle2, AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PageHeader } from "@/components/page-header"
import { useAuthContext } from "@/lib/auth-context"
import { useAuth } from "@/hooks/use-auth"
import { useHealth } from "@/hooks/use-health"
import { api, parseApiError } from "@/lib/api-client"
import { supportedLanguages } from "@/lib/i18n"

export const Route = createLazyFileRoute("/settings/general")({
  component: SettingsGeneralPage,
})

function SettingsGeneralPage() {
  const { t } = useTranslation("settings")

  return (
    <div className="space-y-6">
      <PageHeader title={t("tabs.profile")} description={t("description")} />
      <ProfileSection />
      <LanguageSection />
    </div>
  )
}

function ProfileSection() {
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
    <>
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
    </>
  )
}

function LanguageSection() {
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
