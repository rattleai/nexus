import { useState } from "react"
import { DollarSign, Pencil, Plus, Trash2 } from "lucide-react"
import {
  usePricingRules,
  useDeletePricingRule,
  useUpdatePricingRule,
} from "@/hooks/use-pricing-rules"
import { useCharacteristicAssignments } from "@/hooks/use-characteristics"
import { PricingRuleFormDialog } from "./pricing-rule-form-dialog"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import type { PricingRule, PricingRuleType } from "@/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductPricingProps {
  productId: string
}

// ── Rule type badge mapping ─────────────────────────────

const ruleTypeVariant: Record<
  PricingRuleType,
  "default" | "secondary" | "outline" | "destructive"
> = {
  base_price: "default",
  option_surcharge: "secondary",
  volume_discount: "outline",
  conditional: "secondary",
  formula: "outline",
  tiered: "secondary",
  margin: "destructive",
}

// ── Helper: extract display amount from expression ──────

function extractDisplayAmount(expression: Record<string, unknown>): string {
  if ("amount" in expression && typeof expression.amount === "number") {
    return `$${expression.amount.toFixed(2)}`
  }
  if ("percentage" in expression && typeof expression.percentage === "number") {
    return `${expression.percentage}%`
  }
  if (
    "base_amount" in expression &&
    typeof expression.base_amount === "number"
  ) {
    return `$${(expression.base_amount as number).toFixed(2)}`
  }
  return "\u2014"
}

// ── Component ───────────────────────────────────────────

export function ProductPricing({ productId }: ProductPricingProps) {
  const { data: rulesData, isLoading } = usePricingRules(productId)
  const deleteRule = useDeletePricingRule()
  const updateRule = useUpdatePricingRule()
  const { data: charsData } = useCharacteristicAssignments(productId)

  const [ruleDialogOpen, setRuleDialogOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<PricingRule | null>(null)

  const rules = (rulesData?.items ?? []).sort((a, b) => a.priority - b.priority)
  const characteristics = charsData?.items ?? []

  const handleNewRule = () => {
    setEditingRule(null)
    setRuleDialogOpen(true)
  }

  const handleEditRule = (rule: PricingRule) => {
    setEditingRule(rule)
    setRuleDialogOpen(true)
  }

  const handleDeleteRule = (id: string) => {
    deleteRule.mutate(id)
  }

  const handleToggleActive = (rule: PricingRule) => {
    updateRule.mutate({
      id: rule.id,
      data: { is_active: !rule.is_active },
    })
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div className="space-y-1">
            <CardTitle>Pricing Rules</CardTitle>
            <CardDescription>
              Pricing rules are evaluated in priority order to compute the final
              price.
            </CardDescription>
          </div>
          <Button size="sm" className="gap-1" onClick={handleNewRule}>
            <Plus className="h-4 w-4" />
            New Rule
          </Button>
        </CardHeader>

        <CardContent>
          {rules.length === 0 ? (
            <EmptyState
              icon={DollarSign}
              title="No pricing rules"
              description="Add pricing rules to calculate product prices based on configuration selections."
              action={
                <Button variant="outline" size="sm" onClick={handleNewRule}>
                  <Plus className="h-4 w-4 mr-1" />
                  Add First Rule
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">Priority</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Currency</TableHead>
                  <TableHead>Active</TableHead>
                  <TableHead className="w-24 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell className="text-center font-mono text-sm">
                      {rule.priority}
                    </TableCell>
                    <TableCell>
                      <div>
                        <span className="text-sm font-medium">
                          {rule.name}
                        </span>
                        {rule.description && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {rule.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={ruleTypeVariant[rule.rule_type]}>
                        {rule.rule_type.replace(/_/g, " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {extractDisplayAmount(rule.expression)}
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-muted-foreground uppercase">
                        {rule.currency}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={rule.is_active}
                        onCheckedChange={() => handleToggleActive(rule)}
                        aria-label={`Toggle ${rule.name} active state`}
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => handleEditRule(rule)}
                          aria-label={`Edit ${rule.name}`}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <ConfirmDialog
                          title="Delete Pricing Rule"
                          description={`Are you sure you want to delete "${rule.name}"? This action cannot be undone.`}
                          confirmLabel="Delete"
                          variant="destructive"
                          onConfirm={() => handleDeleteRule(rule.id)}
                        >
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            aria-label={`Delete ${rule.name}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </ConfirmDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <PricingRuleFormDialog
        open={ruleDialogOpen}
        onOpenChange={setRuleDialogOpen}
        productId={productId}
        editRule={editingRule}
        characteristics={characteristics}
      />
    </>
  )
}
