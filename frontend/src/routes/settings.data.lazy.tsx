import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { PageHeader } from "@/components/page-header"
import { useExportTenantData, useExportAccountData } from "@/hooks/use-usage"
import { parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/settings/data")({
  component: SettingsDataPage,
})

function SettingsDataPage() {
  const { t } = useTranslation("settings")
  const exportTenant = useExportTenantData()
  const exportAccount = useExportAccountData()
  const [format, setFormat] = useState<"json" | "csv">("json")

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
    <div className="space-y-6">
      <PageHeader title={t("tabs.data")} />
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
    </div>
  )
}
