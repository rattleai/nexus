import { useTranslation } from "react-i18next"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"

export function GettingStartedCard() {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("getting_started.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-gray-600 mt-2">
          {t("getting_started.description")}
        </p>
      </CardContent>
    </Card>
  )
}
