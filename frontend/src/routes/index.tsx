import { createFileRoute, Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  Briefcase,
  Key,
  Users,
  HardDrive,
  Heart,
  Upload,
  Plus,
  ArrowRight,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { StatCard } from "@/components/stat-card"
import { LoadingState } from "@/components/loading-state"
import { useAuth } from "@/hooks/use-auth"
import { useJobs } from "@/hooks/use-jobs"
import { useHealth } from "@/hooks/use-health"
import { useUsage } from "@/hooks/use-usage"
import { formatBytes, formatDateTime, formatCompactNumber } from "@/lib/format"
import type { JobStatus } from "@/types/api"

export const Route = createFileRoute("/")({
  component: Dashboard,
})

const statusColor: Record<JobStatus, string> = {
  pending: "bg-yellow-500",
  processing: "bg-blue-500",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
}

function Dashboard() {
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <LandingPage />
  }

  return <AuthenticatedDashboard />
}

function LandingPage() {
  const { t } = useTranslation("dashboard")
  const { t: tc } = useTranslation("common")
  return (
    <div className="space-y-12 py-8">
      {/* Hero */}
      <div className="text-center space-y-4 max-w-2xl mx-auto">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          {t("landing.hero_title")}
        </h1>
        <p className="text-lg text-muted-foreground">
          {t("landing.hero_subtitle")}
        </p>
        <div className="flex gap-3 justify-center pt-2">
          <Button size="lg" asChild>
            <Link to="/login">{t("landing.cta_sign_in")}</Link>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link to="/register">{t("landing.cta_register")}</Link>
          </Button>
        </div>
      </div>

      {/* Feature cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Briefcase className="h-8 w-8 mx-auto text-primary" />
            <h3 className="font-semibold">{t("guest.async_jobs_title")}</h3>
            <p className="text-sm text-muted-foreground">
              {t("guest.async_jobs_desc")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Key className="h-8 w-8 mx-auto text-primary" />
            <h3 className="font-semibold">{t("guest.api_keys_title")}</h3>
            <p className="text-sm text-muted-foreground">
              {t("guest.api_keys_desc")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Users className="h-8 w-8 mx-auto text-primary" />
            <h3 className="font-semibold">{t("guest.team_mgmt_title")}</h3>
            <p className="text-sm text-muted-foreground">
              {t("guest.team_mgmt_desc")}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function AuthenticatedDashboard() {
  const { data: usage, isLoading: usageLoading } = useUsage()
  const { data: jobs } = useJobs()
  const { data: health } = useHealth()
  const { t } = useTranslation("dashboard")
  const { t: tc } = useTranslation("common")

  const recentJobs = jobs?.items?.slice(0, 5) ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("authenticated.title")}</h1>
        <p className="mt-1 text-muted-foreground">{t("authenticated.subtitle")}</p>
      </div>

      {usageLoading ? (
        <LoadingState variant="skeleton" rows={1} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title={t("authenticated.total_jobs")}
            value={formatCompactNumber(usage?.jobs?.used ?? 0)}
            icon={Briefcase}
            description={
              usage?.jobs?.limit ? tc("labels.of_limit", { limit: formatCompactNumber(usage.jobs.limit) }) : tc("status.unlimited")
            }
          />
          <StatCard
            title={t("authenticated.api_keys")}
            value={usage?.api_keys?.used ?? 0}
            icon={Key}
            description={
              usage?.api_keys?.limit
                ? tc("labels.of_limit", { limit: usage.api_keys.limit })
                : tc("status.unlimited")
            }
          />
          <StatCard
            title={t("authenticated.team_members")}
            value={usage?.team_members?.used ?? 0}
            icon={Users}
            description={
              usage?.team_members?.limit
                ? tc("labels.of_limit", { limit: usage.team_members.limit })
                : tc("status.unlimited")
            }
          />
          <StatCard
            title={t("authenticated.storage")}
            value={formatBytes(usage?.storage_bytes?.used ?? 0)}
            icon={HardDrive}
            description={
              usage?.storage_bytes?.limit
                ? tc("labels.of_limit", { limit: formatBytes(usage.storage_bytes.limit) })
                : tc("status.unlimited")
            }
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">{t("authenticated.recent_activity")}</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/jobs">
                {tc("buttons.view_all")} <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {recentJobs.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t("authenticated.no_recent_activity")}
              </p>
            ) : (
              <div className="space-y-3">
                {recentJobs.map((job) => (
                  <div key={job.id} className="flex items-center gap-3">
                    <div className={`h-2 w-2 rounded-full ${statusColor[job.status]}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{job.type}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(job.created_at)}
                      </p>
                    </div>
                    <Badge
                      variant={
                        job.status === "completed"
                          ? "default"
                          : job.status === "failed"
                            ? "destructive"
                            : "secondary"
                      }
                    >
                      {tc(`status.${job.status}`)}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Heart className="h-4 w-4" />
              {t("authenticated.service_health")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {health ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div
                    className={`h-3 w-3 rounded-full ${
                      health.status === "ok" ? "bg-emerald-500" : "bg-amber-500"
                    }`}
                  />
                  <span className="text-sm font-medium capitalize">{health.status}</span>
                  <span className="text-xs text-muted-foreground ml-auto">
                    v{health.version}
                  </span>
                </div>
                {Object.entries(health.services ?? {}).map(([name, ok]) => (
                  <div key={name} className="flex items-center gap-2">
                    <div
                      className={`h-2 w-2 rounded-full ${
                        ok ? "bg-emerald-500" : "bg-red-500"
                      }`}
                    />
                    <span className="text-sm text-muted-foreground capitalize">{name}</span>
                  </div>
                ))}
              </div>
            ) : (
              <LoadingState variant="inline" />
            )}
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">{t("authenticated.quick_actions")}</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/jobs">
              <Plus className="mr-2 h-4 w-4" />
              {t("authenticated.create_job")}
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/files">
              <Upload className="mr-2 h-4 w-4" />
              {t("authenticated.upload_file")}
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/team">
              <Users className="mr-2 h-4 w-4" />
              {t("authenticated.manage_team")}
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/api-keys">
              <Key className="mr-2 h-4 w-4" />
              {t("authenticated.api_keys")}
            </Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
