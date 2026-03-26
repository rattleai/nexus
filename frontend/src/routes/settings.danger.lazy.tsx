import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { PageHeader } from "@/components/page-header"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { useDeleteAccount } from "@/hooks/use-usage"
import { parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/settings/danger")({
  component: SettingsDangerPage,
})

function SettingsDangerPage() {
  const { t } = useTranslation("settings")
  const deleteAccount = useDeleteAccount()

  return (
    <div className="space-y-6">
      <PageHeader title={t("tabs.danger")} />
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">{t("danger.title")}</CardTitle>
          <CardDescription>{t("danger.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm text-muted-foreground">{t("danger.delete_info")}</p>
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
    </div>
  )
}
