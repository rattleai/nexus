import { createLazyFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import { CreditCard, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { AuthGuard } from "@/components/auth/auth-guard"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { PlanBadge } from "@/components/billing/plan-badge"
import { PricingTable } from "@/components/billing/pricing-table"
import {
  useSubscription,
  usePlans,
  useCancelSubscription,
  useBillingPortal,
  useCreateCheckout,
} from "@/hooks/use-billing"
import { useUsage } from "@/hooks/use-usage"
import { parseApiError } from "@/lib/api-client"
import { formatDate, formatBytes } from "@/lib/format"
import type { UsageMetric } from "@/types/api"
import { cn } from "@/lib/utils"

export const Route = createLazyFileRoute("/billing")({
  component: BillingPage,
})

const usageLabels: Record<string, string> = {
  jobs: "Jobs",
  api_keys: "API Keys",
  team_members: "Team Members",
  storage_bytes: "Storage",
}

function UsageBar({ label, metric, isBytes }: { label: string; metric: UsageMetric; isBytes?: boolean }) {
  const percent = metric.limit ? Math.min((metric.used / metric.limit) * 100, 100) : 0
  const isWarning = percent >= 80 && percent < 100
  const isAlert = percent >= 100

  const formatValue = (v: number) => (isBytes ? formatBytes(v) : String(v))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className={cn(
          "text-muted-foreground",
          isWarning && "text-amber-600 dark:text-amber-400 font-medium",
          isAlert && "text-red-600 dark:text-red-400 font-medium",
        )}>
          {formatValue(metric.used)} / {metric.limit ? formatValue(metric.limit) : "Unlimited"}
        </span>
      </div>
      {metric.limit ? (
        <Progress
          value={percent}
          className={cn(
            isWarning && "[&>div]:bg-amber-500",
            isAlert && "[&>div]:bg-red-500",
          )}
        />
      ) : (
        <Progress value={0} />
      )}
    </div>
  )
}

function BillingPage() {
  const { data: subscription, isLoading: subLoading, error: subError, refetch: subRefetch } = useSubscription()
  const { data: plans, isLoading: plansLoading } = usePlans()
  const { data: usage, isLoading: usageLoading } = useUsage()
  const cancelSubscription = useCancelSubscription()
  const billingPortal = useBillingPortal()
  const createCheckout = useCreateCheckout()

  const handleManageBilling = async () => {
    try {
      const { url } = await billingPortal.mutateAsync()
      window.location.href = url
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleSelectPlan = async (planId: string) => {
    const plan = plans?.find((p) => p.id === planId)
    if (!plan?.stripe_price_id) return
    try {
      const { url } = await createCheckout.mutateAsync({ price_id: plan.stripe_price_id })
      window.location.href = url
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const isLoading = subLoading || plansLoading || usageLoading

  return (
    <AuthGuard requiredRole="admin">
      <div className="space-y-6">
        <PageHeader
          title="Billing"
          description="Manage your subscription and usage."
          actions={
            <Button variant="outline" onClick={handleManageBilling} disabled={billingPortal.isPending}>
              <ExternalLink className="mr-2 h-4 w-4" />
              Manage Billing
            </Button>
          }
        />

        {isLoading ? (
          <LoadingState variant="skeleton" rows={4} />
        ) : subError ? (
          <ErrorState
            message={subError instanceof Error ? subError.message : "Failed to load billing data."}
            onRetry={() => subRefetch()}
          />
        ) : (
          <>
            {/* Current Plan */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-3">
                  <CreditCard className="h-5 w-5" />
                  Current Plan
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <PlanBadge
                      plan={subscription?.plan?.name ?? "Free"}
                      status={subscription?.status as "active" | "past_due" | "canceled" | "trialing" | undefined}
                    />
                    {subscription?.current_period_start && subscription.current_period_end && (
                      <p className="text-sm text-muted-foreground">
                        {formatDate(subscription.current_period_start)} &mdash;{" "}
                        {formatDate(subscription.current_period_end)}
                      </p>
                    )}
                    {subscription?.cancel_at_period_end && (
                      <p className="text-sm text-amber-600 dark:text-amber-400 font-medium">
                        Cancels at end of billing period
                      </p>
                    )}
                  </div>
                  {subscription?.status === "active" && !subscription.cancel_at_period_end && (
                    <ConfirmDialog
                      title="Cancel Subscription"
                      description="Are you sure you want to cancel your subscription? You'll retain access until the end of your current billing period."
                      variant="destructive"
                      confirmLabel="Cancel Subscription"
                      onConfirm={async () => {
                        try {
                          await cancelSubscription.mutateAsync()
                          toast.success("Subscription canceled")
                        } catch (err) {
                          const e = await parseApiError(err)
                          toast.error(e.detail)
                        }
                      }}
                    >
                      <Button variant="destructive" size="sm">
                        Cancel Subscription
                      </Button>
                    </ConfirmDialog>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Usage */}
            {usage && (
              <Card>
                <CardHeader>
                  <CardTitle>Usage</CardTitle>
                  <CardDescription>Current resource usage for your workspace.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  {(Object.keys(usageLabels) as Array<keyof typeof usageLabels>).map((key) => {
                    const metric = usage[key as keyof typeof usage]
                    if (!metric) return null
                    return (
                      <UsageBar
                        key={key}
                        label={usageLabels[key]}
                        metric={metric}
                        isBytes={key === "storage_bytes"}
                      />
                    )
                  })}
                </CardContent>
              </Card>
            )}

            {/* Pricing Table */}
            {plans && plans.length > 0 && (
              <div className="space-y-4">
                <h2 className="text-lg font-semibold">Available Plans</h2>
                <PricingTable
                  plans={plans.map((p) => ({
                    id: p.id,
                    name: p.name,
                    price: p.price_monthly,
                    interval: "month" as const,
                    features: p.features,
                    isPopular: p.name.toLowerCase() === "pro",
                  }))}
                  currentPlanId={subscription?.plan?.id ?? null}
                  onSelectPlan={handleSelectPlan}
                />
              </div>
            )}
          </>
        )}
      </div>
    </AuthGuard>
  )
}
