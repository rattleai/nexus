import { useState } from "react"
import { createLazyFileRoute, Link } from "@tanstack/react-router"
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

export const Route = createLazyFileRoute("/forgot-password")({
  component: ForgotPasswordPage,
})

type ForgotPasswordFormValues = z.infer<ReturnType<typeof makeForgotPasswordSchema>>

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function makeForgotPasswordSchema(tv: any) {
  return z.object({
    email: z.string().min(1, tv("email_required")).email(tv("invalid_email")),
  })
}

function ForgotPasswordPage() {
  const { t } = useTranslation("auth")
  const { t: tv } = useTranslation("validation")
  const [submitted, setSubmitted] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const forgotPasswordSchema = makeForgotPasswordSchema(tv)

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  })

  const onSubmit = async (data: ForgotPasswordFormValues) => {
    setIsSubmitting(true)
    try {
      await api.post("auth/forgot-password", { json: { email: data.email } })
      setSubmitted(true)
      toast.success(t("forgot_password.success"))
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
          <CardTitle>{t("forgot_password.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {submitted ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">
                {t("forgot_password.success")}
              </p>
              <Link to="/login" className="text-sm text-primary underline">
                {t("forgot_password.back_to_sign_in")}
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
              {errors.root && (
                <p className="text-sm text-destructive" role="alert">
                  {errors.root.message}
                </p>
              )}
              <div className="space-y-2">
                <Label htmlFor="email">{t("forgot_password.email_label")}</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder={t("forgot_password.email_placeholder")}
                  autoComplete="email"
                  autoFocus
                  disabled={isSubmitting}
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
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? t("forgot_password.submitting") : t("forgot_password.submit")}
              </Button>
              <p className="text-sm text-center text-muted-foreground">
                <Link to="/login" className="text-primary underline">
                  {t("forgot_password.back_to_sign_in")}
                </Link>
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
