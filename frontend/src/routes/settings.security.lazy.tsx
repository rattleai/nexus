import { useEffect, useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { CheckCircle2, Github, Link2, Unlink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { PageHeader } from "@/components/page-header"
import { useAuthContext } from "@/lib/auth-context"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/settings/security")({
  component: SettingsSecurityPage,
})

function SettingsSecurityPage() {
  const { t } = useTranslation("settings")

  return (
    <div className="space-y-6">
      <PageHeader title={t("tabs.security")} />
      <SecuritySection />
      <ConnectedAccountsSection />
    </div>
  )
}

function SecuritySection() {
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

interface OAuthAccountInfo {
  id: string
  provider: string
  provider_user_id: string
  created_at: string
}

const ALLOWED_PROVIDERS = ["google", "github"] as const

function ConnectedAccountsSection() {
  const { t } = useTranslation("settings")
  const [accounts, setAccounts] = useState<OAuthAccountInfo[]>([])
  const [providers, setProviders] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [unlinking, setUnlinking] = useState<string | null>(null)
  const { user } = useAuthContext()

  const fetchData = async () => {
    try {
      const [accts, provs] = await Promise.all([
        api.get("auth/oauth/accounts").json<OAuthAccountInfo[]>(),
        api.get("auth/oauth/providers").json<{ providers: string[] }>(),
      ])
      setAccounts(accts)
      setProviders(provs.providers)
    } catch {
      // OAuth not configured
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  if (loading || providers.length === 0) return null

  const linkedProviders = accounts.map((a) => a.provider)

  const handleLink = async (provider: string) => {
    if (!ALLOWED_PROVIDERS.includes(provider as (typeof ALLOWED_PROVIDERS)[number])) return
    try {
      const res = await api.post(`auth/oauth/${provider}/link`).json<{ url: string }>()
      window.location.href = res.url
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleUnlink = async (provider: string) => {
    if (!ALLOWED_PROVIDERS.includes(provider as (typeof ALLOWED_PROVIDERS)[number])) return
    if (unlinking) return
    setUnlinking(provider)
    try {
      await api.delete(`auth/oauth/${provider}/unlink`)
      toast.success(t("connected_accounts.unlink_success"))
      fetchData()
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    } finally {
      setUnlinking(null)
    }
  }

  const providerIcon = (provider: string) => {
    if (provider === "github") return <Github className="h-4 w-4" />
    if (provider === "google") {
      return (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
        </svg>
      )
    }
    return <Link2 className="h-4 w-4" />
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("connected_accounts.title")}</CardTitle>
        <CardDescription>{t("connected_accounts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {providers.map((provider) => {
          const isLinked = linkedProviders.includes(provider)
          return (
            <div key={provider} className="flex items-center justify-between p-3 border rounded-lg">
              <div className="flex items-center gap-3">
                {providerIcon(provider)}
                <span className="font-medium capitalize">{provider}</span>
                {isLinked && (
                  <Badge variant="default" className="gap-1">
                    <CheckCircle2 className="h-3 w-3" />
                    Connected
                  </Badge>
                )}
              </div>
              {isLinked ? (
                <Button variant="outline" size="sm" onClick={() => handleUnlink(provider)} disabled={unlinking === provider}>
                  <Unlink className="mr-1 h-3 w-3" />
                  {t("connected_accounts.unlink")}
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={() => handleLink(provider)}>
                  <Link2 className="mr-1 h-3 w-3" />
                  {t("connected_accounts.link")}
                </Button>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
