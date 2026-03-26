import { createLazyFileRoute } from "@tanstack/react-router"
import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  BookOpen,
  Key,
  KeyRound,
  Webhook,
  ExternalLink,
  Terminal,
  Code2,
  ArrowRight,
} from "lucide-react"
import { AuthGuard } from "@/components/auth/auth-guard"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export const Route = createLazyFileRoute("/developers")({
  component: DevelopersPage,
})

const API_DOCS_URL = "/api/docs"

function DevelopersPage() {
  const { t } = useTranslation("developers")
  const { t: tc } = useTranslation("common")

  return (
    <AuthGuard>
      <div className="space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
          <p className="text-muted-foreground mt-1">{t("description")}</p>
        </div>

        {/* Quick links grid */}
        <div className="grid gap-4 md:grid-cols-2">
          {/* API Reference */}
          <Card className="group relative overflow-hidden border transition-colors hover:border-primary/50">
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <BookOpen className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <CardTitle className="text-base">{t("cards.api_reference.title")}</CardTitle>
                </div>
                <Badge variant="secondary" className="text-xs">
                  REST
                </Badge>
              </div>
              <CardDescription>{t("cards.api_reference.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" asChild>
                <a href={API_DOCS_URL} target="_blank" rel="noopener noreferrer">
                  {t("cards.api_reference.action")}
                  <ExternalLink className="ml-2 h-3.5 w-3.5" />
                </a>
              </Button>
            </CardContent>
          </Card>

          {/* API Keys */}
          <Card className="group relative overflow-hidden border transition-colors hover:border-primary/50">
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Key className="h-5 w-5" />
                </div>
                <CardTitle className="text-base">{t("cards.api_keys.title")}</CardTitle>
              </div>
              <CardDescription>{t("cards.api_keys.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" asChild>
                <Link to="/settings/api-keys">
                  {t("cards.api_keys.action")}
                  <ArrowRight className="ml-2 h-3.5 w-3.5" />
                </Link>
              </Button>
            </CardContent>
          </Card>

          {/* Webhooks */}
          <Card className="group relative overflow-hidden border transition-colors hover:border-primary/50">
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Webhook className="h-5 w-5" />
                </div>
                <CardTitle className="text-base">{t("cards.webhooks.title")}</CardTitle>
              </div>
              <CardDescription>{t("cards.webhooks.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" asChild>
                <Link to="/settings/webhooks">
                  {t("cards.webhooks.action")}
                  <ArrowRight className="ml-2 h-3.5 w-3.5" />
                </Link>
              </Button>
            </CardContent>
          </Card>

          {/* Provider Keys (BYOK) */}
          <Card className="group relative overflow-hidden border transition-colors hover:border-primary/50">
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <KeyRound className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <CardTitle className="text-base">{t("cards.provider_keys.title")}</CardTitle>
                </div>
                <Badge variant="secondary" className="text-xs">
                  BYOK
                </Badge>
              </div>
              <CardDescription>{t("cards.provider_keys.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" asChild>
                <Link to="/settings/providers">
                  {t("cards.provider_keys.action")}
                  <ArrowRight className="ml-2 h-3.5 w-3.5" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Getting started section */}
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">{t("getting_started.title")}</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {/* Quick start */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Terminal className="h-5 w-5 text-muted-foreground" />
                  <CardTitle className="text-base">{t("getting_started.quickstart.title")}</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-lg bg-muted p-4 font-mono text-sm space-y-2">
                  <p className="text-muted-foreground"># {t("getting_started.quickstart.comment")}</p>
                  <p>
                    <span className="text-primary">curl</span> -X GET /api/v1/health \
                  </p>
                  <p className="pl-4">
                    -H <span className="text-green-600 dark:text-green-400">"Authorization: Bearer YOUR_API_KEY"</span>
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* OpenAPI spec */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Code2 className="h-5 w-5 text-muted-foreground" />
                  <CardTitle className="text-base">{t("getting_started.openapi.title")}</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {t("getting_started.openapi.description")}
                </p>
                <Button variant="outline" size="sm" asChild>
                  <a href="/api/v1/openapi.json" target="_blank" rel="noopener noreferrer">
                    {t("getting_started.openapi.action")}
                    <ExternalLink className="ml-2 h-3.5 w-3.5" />
                  </a>
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </AuthGuard>
  )
}
