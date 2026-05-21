import { createLazyFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthContext } from "@/lib/auth-context"
import { parseApiError } from "@/lib/api-client"
import { SocialLoginButtons } from "@/components/auth/social-login-buttons"

export const Route = createLazyFileRoute("/login")({
  component: LoginPage,
})

function LoginPage() {
  const { login, isLoading } = useAuthContext()
  const navigate = useNavigate()
  const { t } = useTranslation("auth")
  const { t: tv } = useTranslation("validation")

  const loginSchema = z.object({
    email: z.string().min(1, tv("email_required")).email(tv("invalid_email")),
    password: z.string().min(1, tv("password_required")),
  })

  type LoginFormValues = z.infer<typeof loginSchema>

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  })

  const onSubmit = async (data: LoginFormValues) => {
    try {
      await login(data.email, data.password)
      toast.success(t("sign_in.success"))
      navigate({ to: "/" })
    } catch (err) {
      const apiError = await parseApiError(err)
      setError("root", { message: apiError.detail })
    }
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("sign_in.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            {errors.root && (
              <p className="text-sm text-destructive" role="alert">
                {errors.root.message}
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">{t("sign_in.email_label")}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t("sign_in.email_placeholder")}
                autoComplete="email"
                autoFocus
                disabled={isLoading}
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? "email-error" : undefined}
                {...register("email")}
              />
              {errors.email && (
                <p id="email-error" className="text-sm text-destructive" role="alert">
                  {errors.email.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t("sign_in.password_label")}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                disabled={isLoading}
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? "password-error" : undefined}
                {...register("password")}
              />
              {errors.password && (
                <p id="password-error" className="text-sm text-destructive" role="alert">
                  {errors.password.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? t("sign_in.submitting") : t("sign_in.submit")}
            </Button>
            <SocialLoginButtons mode="login" disabled={isLoading} />
            <div className="text-sm text-center text-muted-foreground space-y-1">
              <p>
                {t("sign_in.no_account")}{" "}
                <Link to="/register" className="text-primary underline">
                  {t("sign_in.register_link")}
                </Link>
              </p>
              <p>
                <Link to="/forgot-password" className="text-primary underline">
                  {t("sign_in.forgot_password")}
                </Link>
              </p>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
