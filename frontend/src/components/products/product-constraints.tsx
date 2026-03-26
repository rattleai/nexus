import { useTranslation } from "react-i18next"
import { ShieldCheck, AlertTriangle } from "lucide-react"
import {
  useConstraintRules,
  useConstraintGroups,
  useUpdateConstraintRule,
} from "@/hooks/use-constraints"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import type { ConstraintRule, ConstraintType } from "@/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductConstraintsProps {
  productId: string
}

// ── Constraint type badge mapping ───────────────────────

const constraintTypeVariant: Record<
  ConstraintType,
  "default" | "secondary" | "outline" | "destructive"
> = {
  requires: "default",
  excludes: "destructive",
  selection_condition: "secondary",
  default_value: "outline",
  formula: "secondary",
  table: "outline",
}

// ── Component ───────────────────────────────────────────

export function ProductConstraints({ productId }: ProductConstraintsProps) {
  const { t } = useTranslation()
  const { data: rulesData, isLoading: loadingRules } = useConstraintRules({
    product_id: productId,
  })
  const { data: groupsData, isLoading: loadingGroups } = useConstraintGroups(productId)
  const updateRule = useUpdateConstraintRule()

  const rules = rulesData?.items ?? []
  const groups = groupsData?.items ?? []

  function handleToggleActive(rule: ConstraintRule) {
    updateRule.mutate({
      id: rule.id,
      data: { is_active: !rule.is_active },
    })
  }

  if (loadingRules || loadingGroups) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (rules.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("products.constraints", "Constraints")}</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={ShieldCheck}
            title={t("products.noConstraints", "No constraint rules")}
            description={t(
              "products.noConstraintsDescription",
              "Add constraint rules to enforce configuration logic for this product.",
            )}
          />
        </CardContent>
      </Card>
    )
  }

  // Group rules by constraint group
  const groupMap = new Map(groups.map((g) => [g.id, g]))
  const ungroupedRules = rules.filter((r) => !r.group_id)
  const groupedRules = new Map<string, ConstraintRule[]>()

  for (const rule of rules) {
    if (rule.group_id) {
      const existing = groupedRules.get(rule.group_id) ?? []
      existing.push(rule)
      groupedRules.set(rule.group_id, existing)
    }
  }

  return (
    <div className="space-y-4">
      {/* Grouped rules */}
      {Array.from(groupedRules.entries()).map(([groupId, groupRules]) => {
        const group = groupMap.get(groupId)
        return (
          <Card key={groupId}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="space-y-1.5">
                  <CardTitle className="text-base">
                    {group?.name ?? t("products.unknownGroup", "Unknown Group")}
                  </CardTitle>
                  {group?.description && (
                    <CardDescription>{group.description}</CardDescription>
                  )}
                </div>
                {group && !group.is_active && (
                  <Badge variant="outline">
                    <AlertTriangle className="mr-1 h-3 w-3" />
                    {t("common.inactive", "Inactive")}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {groupRules
                .sort((a, b) => a.priority - b.priority)
                .map((rule) => (
                  <ConstraintRuleRow
                    key={rule.id}
                    rule={rule}
                    onToggle={handleToggleActive}
                    isPending={updateRule.isPending}
                    t={t}
                  />
                ))}
            </CardContent>
          </Card>
        )
      })}

      {/* Ungrouped rules */}
      {ungroupedRules.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("products.ungroupedRules", "Ungrouped Rules")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {ungroupedRules
              .sort((a, b) => a.priority - b.priority)
              .map((rule) => (
                <ConstraintRuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={handleToggleActive}
                  isPending={updateRule.isPending}
                  t={t}
                />
              ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── ConstraintRuleRow sub-component ─────────────────────

function ConstraintRuleRow({
  rule,
  onToggle,
  isPending,
  t,
}: {
  rule: ConstraintRule
  onToggle: (rule: ConstraintRule) => void
  isPending: boolean
  t: (key: string, fallback: string) => string
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border p-3">
      <div className="flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{rule.name}</span>
          <Badge variant={constraintTypeVariant[rule.constraint_type]}>
            {rule.constraint_type}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {t("products.priority", "Priority")}: {rule.priority}
          </span>
        </div>
        {rule.description && (
          <p className="text-xs text-muted-foreground">{rule.description}</p>
        )}
      </div>
      <Switch
        checked={rule.is_active}
        onCheckedChange={() => onToggle(rule)}
        disabled={isPending}
      />
    </div>
  )
}
