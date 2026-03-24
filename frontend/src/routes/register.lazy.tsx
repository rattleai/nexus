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

export const Route = createLazyFileRoute("/register")({
  component: RegisterPage,
})

function RegisterPage() {
  const { register: registerUser, isLoading } = useAuthContext()
  const navigate = useNavigate()
  const { t } = useTranslation("auth")
  const { t: tv } = useTranslation("validation")

  const registerSchema = z
    .object({
      email: z.string().min(1, tv("email_required")).email(tv("invalid_email")),
      displayName: z.string().min(1, tv("display_name_required")),
      tenantSlug: z
        .string()
        .min(1, tv("org_slug_required"))
        .regex(
          /^[a-z0-9][a-z0-9-]*[a-z0-9]$/,
          tv("org_slug_format"),
        ),
      password: z
        .string()
        .min(8, tv("password_min_length", { count: 8 }))
        .regex(/[a-z]/, tv("password_lowercase"))
        .regex(/[A-Z]/, tv("password_uppercase"))
        .regex(/\d/, tv("password_digit")),
      confirmPassword: z.string().min(1, tv("confirm_password_required")),
    })
    .refine((data) => data.password === data.confirmPassword, {
      message: tv("passwords_not_match"),
      path: ["confirmPassword"],
    })

  type RegisterFormValues = z.infer<typeof registerSchema>

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      email: "",
      displayName: "",
      tenantSlug: "",
      password: "",
      confirmPassword: "",
    },
  })

  const onSubmit = async (data: RegisterFormValues) => {
    try {
      await registerUser(data.email, data.password, data.displayName, data.tenantSlug)
      toast.success(t("register.success"))
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
          <CardTitle>{t("register.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            {errors.root && (
              <p className="text-sm text-destructive" role="alert">
                {errors.root.message}
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">{t("register.email_label")}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t("register.email_placeholder")}
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
              <Label htmlFor="displayName">{t("register.display_name_label")}</Label>
              <Input
                id="displayName"
                type="text"
                placeholder={t("register.display_name_placeholder")}
                autoComplete="name"
                disabled={isLoading}
                aria-invalid={!!errors.displayName}
                aria-describedby={errors.displayName ? "displayName-error" : undefined}
                {...register("displayName")}
              />
              {errors.displayName && (
                <p id="displayName-error" className="text-sm text-destructive" role="alert">
                  {errors.displayName.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="tenantSlug">{t("register.org_slug_label")}</Label>
              <Input
                id="tenantSlug"
                type="text"
                placeholder={t("register.org_slug_placeholder")}
                disabled={isLoading}
                aria-invalid={!!errors.tenantSlug}
                aria-describedby={errors.tenantSlug ? "tenantSlug-error" : undefined}
                {...register("tenantSlug")}
              />
              {errors.tenantSlug && (
                <p id="tenantSlug-error" className="text-sm text-destructive" role="alert">
                  {errors.tenantSlug.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t("register.password_label")}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
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
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">{t("register.confirm_password_label")}</Label>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                disabled={isLoading}
                aria-invalid={!!errors.confirmPassword}
                aria-describedby={errors.confirmPassword ? "confirmPassword-error" : undefined}
                {...register("confirmPassword")}
              />
              {errors.confirmPassword && (
                <p id="confirmPassword-error" className="text-sm text-destructive" role="alert">
                  {errors.confirmPassword.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? t("register.submitting") : t("register.submit")}
            </Button>
            <SocialLoginButtons mode="register" disabled={isLoading} />
            <p className="text-sm text-center text-muted-foreground">
              {t("register.has_account")}{" "}
              <Link to="/login" className="text-primary underline">
                {t("register.sign_in_link")}
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
