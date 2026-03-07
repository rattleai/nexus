import { createFileRoute, Link } from "@tanstack/react-router"
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
    return <GuestDashboard />
  }

  return <AuthenticatedDashboard />
}

function GuestDashboard() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Welcome to your platform</h1>
        <p className="mt-1 text-muted-foreground">
          Sign in or enter your API key to get started.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Briefcase className="h-8 w-8 mx-auto text-muted-foreground" />
            <h3 className="font-semibold">Async Jobs</h3>
            <p className="text-sm text-muted-foreground">
              Create and manage background processing jobs.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Key className="h-8 w-8 mx-auto text-muted-foreground" />
            <h3 className="font-semibold">API Keys</h3>
            <p className="text-sm text-muted-foreground">
              Secure programmatic access to the platform.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 text-center space-y-3">
            <Users className="h-8 w-8 mx-auto text-muted-foreground" />
            <h3 className="font-semibold">Team Management</h3>
            <p className="text-sm text-muted-foreground">
              Invite and manage team members with roles.
            </p>
          </CardContent>
        </Card>
      </div>
      <div className="flex gap-3">
        <Button asChild>
          <Link to="/login">Sign in</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link to="/register">Create account</Link>
        </Button>
      </div>
    </div>
  )
}

function AuthenticatedDashboard() {
  const { data: usage, isLoading: usageLoading } = useUsage()
  const { data: jobs } = useJobs()
  const { data: health } = useHealth()

  const recentJobs = jobs?.items?.slice(0, 5) ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="mt-1 text-muted-foreground">Overview of your workspace.</p>
      </div>

      {usageLoading ? (
        <LoadingState variant="skeleton" rows={1} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Total Jobs"
            value={formatCompactNumber(usage?.jobs.used ?? 0)}
            icon={Briefcase}
            description={
              usage?.jobs.limit ? `of ${formatCompactNumber(usage.jobs.limit)} limit` : "unlimited"
            }
          />
          <StatCard
            title="API Keys"
            value={usage?.api_keys.used ?? 0}
            icon={Key}
            description={
              usage?.api_keys.limit
                ? `of ${usage.api_keys.limit} limit`
                : "unlimited"
            }
          />
          <StatCard
            title="Team Members"
            value={usage?.team_members.used ?? 0}
            icon={Users}
            description={
              usage?.team_members.limit
                ? `of ${usage.team_members.limit} limit`
                : "unlimited"
            }
          />
          <StatCard
            title="Storage"
            value={formatBytes(usage?.storage_bytes.used ?? 0)}
            icon={HardDrive}
            description={
              usage?.storage_bytes.limit
                ? `of ${formatBytes(usage.storage_bytes.limit)} limit`
                : "unlimited"
            }
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">Recent Activity</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/jobs">
                View all <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {recentJobs.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No recent activity
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
                      {job.status}
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
              Service Health
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
                {Object.entries(health.services).map(([name, ok]) => (
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
        <h2 className="text-lg font-semibold mb-3">Quick Actions</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/jobs">
              <Plus className="mr-2 h-4 w-4" />
              Create Job
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/files">
              <Upload className="mr-2 h-4 w-4" />
              Upload File
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/team">
              <Users className="mr-2 h-4 w-4" />
              Manage Team
            </Link>
          </Button>
          <Button variant="outline" className="h-auto py-3 justify-start" asChild>
            <Link to="/api-keys">
              <Key className="mr-2 h-4 w-4" />
              API Keys
            </Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
