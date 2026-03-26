import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  GitBranch,
  CheckCircle2,
  Circle,
  RefreshCw,
  Rocket,
} from "lucide-react"
import {
  useProductVersions,
  usePublishVersion,
  useActivateVersion,
  useRecompileVersion,
} from "@/hooks/use-products"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import { Timeline, type TimelineItem } from "@/components/ui/timeline"

// ── Types ───────────────────────────────────────────────

interface ProductVersionsProps {
  productId: string
}

// ── Component ───────────────────────────────────────────

export function ProductVersions({ productId }: ProductVersionsProps) {
  const { t } = useTranslation()
  const { data: versionsData, isLoading } = useProductVersions(productId)
  const publishVersion = usePublishVersion()
  const activateVersion = useActivateVersion()
  const recompileVersion = useRecompileVersion()

  const [publishDialogOpen, setPublishDialogOpen] = useState(false)
  const [versionLabel, setVersionLabel] = useState("")

  const versions = versionsData?.items ?? []

  function handlePublish() {
    publishVersion.mutate(
      {
        productId,
        data: { label: versionLabel || null },
      },
      {
        onSuccess: () => {
          setPublishDialogOpen(false)
          setVersionLabel("")
        },
      },
    )
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex gap-4">
              <Skeleton className="h-8 w-8 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-64" />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    )
  }

  // Build timeline items
  const timelineItems: TimelineItem[] = versions
    .sort((a, b) => b.version_number - a.version_number)
    .map((v) => ({
      id: v.id,
      title: `v${v.version_number}${v.label ? ` — ${v.label}` : ""}`,
      description: v.is_active
        ? t("versions.activeVersion", "Currently active version")
        : v.published_at
          ? t("versions.published", "Published")
          : t("versions.draft", "Draft"),
      date: v.published_at
        ? new Date(v.published_at).toLocaleDateString()
        : v.created_at
          ? new Date(v.created_at).toLocaleDateString()
          : undefined,
      icon: v.is_active ? CheckCircle2 : Circle,
      variant: v.is_active ? ("success" as const) : ("default" as const),
    }))

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("products.versions", "Versions")}</CardTitle>
          <CardDescription>
            {t(
              "products.versionsDescription",
              "Product versions capture a snapshot of characteristics, constraints, and pricing.",
            )}
          </CardDescription>
        </div>

        <Dialog open={publishDialogOpen} onOpenChange={setPublishDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Rocket className="mr-2 h-4 w-4" />
              {t("products.publishVersion", "Publish Version")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {t("versions.publishNew", "Publish New Version")}
              </DialogTitle>
              <DialogDescription>
                {t(
                  "versions.publishDescription",
                  "This will create a snapshot of the current product configuration.",
                )}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="version-label">
                {t("versions.label", "Version Label")}
              </Label>
              <Input
                id="version-label"
                value={versionLabel}
                onChange={(e) => setVersionLabel(e.target.value)}
                placeholder={t("versions.labelPlaceholder", "e.g. Initial Release, Q2 Update...")}
              />
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setPublishDialogOpen(false)}
              >
                {t("common.cancel", "Cancel")}
              </Button>
              <Button onClick={handlePublish} disabled={publishVersion.isPending}>
                {publishVersion.isPending
                  ? t("common.publishing", "Publishing...")
                  : t("common.publish", "Publish")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>

      <CardContent>
        {versions.length === 0 ? (
          <EmptyState
            icon={GitBranch}
            title={t("products.noVersions", "No versions published")}
            description={t(
              "products.noVersionsDescription",
              "Publish a version to create a configuration snapshot that can be used in the configurator.",
            )}
          />
        ) : (
          <div className="space-y-6">
            <Timeline items={timelineItems} />

            {/* Version action buttons */}
            <div className="space-y-2">
              {versions
                .sort((a, b) => b.version_number - a.version_number)
                .map((v) => (
                  <div
                    key={v.id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-mono font-medium">
                        v{v.version_number}
                      </span>
                      {v.label && (
                        <span className="text-sm text-muted-foreground">{v.label}</span>
                      )}
                      {v.is_active && (
                        <Badge variant="default">
                          {t("common.active", "Active")}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {!v.is_active && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            activateVersion.mutate({
                              productId,
                              versionId: v.id,
                            })
                          }
                          disabled={activateVersion.isPending}
                        >
                          <CheckCircle2 className="mr-1 h-3 w-3" />
                          {t("versions.activate", "Activate")}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          recompileVersion.mutate({
                            productId,
                            versionId: v.id,
                          })
                        }
                        disabled={recompileVersion.isPending}
                      >
                        <RefreshCw className="mr-1 h-3 w-3" />
                        {t("versions.recompile", "Recompile")}
                      </Button>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
