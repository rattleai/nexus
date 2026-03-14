import { useState } from "react"
import { createLazyFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/reset-password")({
  component: ResetPasswordPage,
})

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function makeResetPasswordSchema(tv: any) {
  return z
    .object({
      new_password: z
        .string()
        .min(8, tv("password_min_length", { count: 8 }))
        .regex(/[a-z]/, tv("password_lowercase"))
        .regex(/[A-Z]/, tv("password_uppercase"))
        .regex(/\d/, tv("password_digit")),
      confirm_password: z.string().min(1, tv("confirm_password_required")),
    })
    .refine((data) => data.new_password === data.confirm_password, {
      message: tv("passwords_not_match"),
      path: ["confirm_password"],
    })
}

type ResetPasswordFormValues = z.infer<ReturnType<typeof makeResetPasswordSchema>>

function ResetPasswordPage() {
  const { t } = useTranslation("auth")
  const { t: tv } = useTranslation("validation")
  const { token } = useSearch({ from: "/reset-password" })
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const resetPasswordSchema = makeResetPasswordSchema(tv)

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: "", confirm_password: "" },
  })

  if (!token) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>{t("reset_password.title")}</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-sm text-destructive" role="alert">
              {t("reset_password.invalid_token")}
            </p>
            <Link to="/forgot-password" className="text-sm text-primary underline">
              {t("reset_password.request_new_link")}
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  const onSubmit = async (data: ResetPasswordFormValues) => {
    setIsSubmitting(true)
    try {
      await api.post("auth/reset-password", {
        json: { token, new_password: data.new_password },
      })
      toast.success(t("reset_password.success"))
      navigate({ to: "/login" })
    } catch (err) {
      const apiError = await parseApiError(err)
      setError("root", { message: apiError.detail })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("reset_password.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            {errors.root && (
              <p className="text-sm text-destructive" role="alert">
                {errors.root.message}
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="new_password">{t("reset_password.new_password_label")}</Label>
              <Input
                id="new_password"
                type="password"
                autoComplete="new-password"
                autoFocus
                disabled={isSubmitting}
                aria-invalid={!!errors.new_password}
                aria-describedby={errors.new_password ? "new_password-error" : undefined}
                {...register("new_password")}
              />
              {errors.new_password && (
                <p id="new_password-error" className="text-sm text-destructive" role="alert">
                  {errors.new_password.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm_password">{t("reset_password.confirm_password_label")}</Label>
              <Input
                id="confirm_password"
                type="password"
                autoComplete="new-password"
                disabled={isSubmitting}
                aria-invalid={!!errors.confirm_password}
                aria-describedby={errors.confirm_password ? "confirm_password-error" : undefined}
                {...register("confirm_password")}
              />
              {errors.confirm_password && (
                <p id="confirm_password-error" className="text-sm text-destructive" role="alert">
                  {errors.confirm_password.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? t("reset_password.submitting") : t("reset_password.submit")}
            </Button>
            <p className="text-sm text-center text-muted-foreground">
              <Link to="/login" className="text-primary underline">
                {t("reset_password.back_to_sign_in")}
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
