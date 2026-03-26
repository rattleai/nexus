import { useEffect, useState, useCallback } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Plus, Trash2 } from "lucide-react"
import {
  useCreatePricingRule,
  useUpdatePricingRule,
} from "@/hooks/use-pricing-rules"
import { ConditionBuilder } from "@/components/condition-builder"
import type { ConditionNode } from "@/components/condition-builder"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { Characteristic, PricingRule, PricingRuleType } from "@/types/configurator"

// ── Constants ────────────────────────────────────────────

const RULE_TYPES: { value: PricingRuleType; label: string }[] = [
  { value: "base_price", label: "Base Price" },
  { value: "option_surcharge", label: "Option Surcharge" },
  { value: "volume_discount", label: "Volume Discount" },
  { value: "conditional", label: "Conditional" },
  { value: "formula", label: "Formula" },
  { value: "tiered", label: "Tiered" },
  { value: "margin", label: "Margin" },
]

// ── Zod Schema ───────────────────────────────────────────

const pricingRuleFormSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  rule_type: z.enum([
    "base_price",
    "option_surcharge",
    "volume_discount",
    "conditional",
    "formula",
    "tiered",
    "margin",
  ]),
  priority: z.coerce.number().int().min(0, "Priority must be >= 0"),
  is_active: z.boolean(),
  currency: z.string().min(1, "Currency is required").max(10),
  effective_from: z.string().nullable().optional(),
  effective_to: z.string().nullable().optional(),
})

type PricingRuleFormValues = z.infer<typeof pricingRuleFormSchema>

// ── Tier interface ───────────────────────────────────────

interface TierRow {
  min: number
  max: number
  value: number
}

// ── Props ────────────────────────────────────────────────

interface PricingRuleFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  productId: string
  editRule?: PricingRule | null
  characteristics: Characteristic[]
}

// ── Helpers: parse expression into form state ────────────

function parseCondition(expr: Record<string, unknown>): ConditionNode | null {
  if (expr.condition && typeof expr.condition === "object") {
    return expr.condition as ConditionNode
  }
  return null
}

function parseTiers(expr: Record<string, unknown>): TierRow[] {
  if (Array.isArray(expr.tiers)) {
    return (expr.tiers as Record<string, unknown>[]).map((t) => ({
      min: typeof t.min === "number" ? t.min : 0,
      max: typeof t.max === "number" ? t.max : 0,
      value: typeof t.discount === "number"
        ? t.discount
        : typeof t.amount === "number"
          ? t.amount
          : 0,
    }))
  }
  return [{ min: 0, max: 0, value: 0 }]
}

// ── Tiers Editor Sub-component ───────────────────────────

function TiersEditor({
  tiers,
  onChange,
  valueLabel,
}: {
  tiers: TierRow[]
  onChange: (tiers: TierRow[]) => void
  valueLabel: string
}) {
  const updateTier = (index: number, field: keyof TierRow, val: number) => {
    const updated = tiers.map((t, i) =>
      i === index ? { ...t, [field]: val } : t,
    )
    onChange(updated)
  }

  const addTier = () => {
    const last = tiers[tiers.length - 1]
    onChange([...tiers, { min: last?.max ?? 0, max: 0, value: 0 }])
  }

  const removeTier = (index: number) => {
    if (tiers.length <= 1) return
    onChange(tiers.filter((_, i) => i !== index))
  }

  return (
    <div className="space-y-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[100px]">Min</TableHead>
            <TableHead className="w-[100px]">Max</TableHead>
            <TableHead className="w-[120px]">{valueLabel}</TableHead>
            <TableHead className="w-[50px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {tiers.map((tier, idx) => (
            <TableRow key={idx}>
              <TableCell className="p-1">
                <Input
                  type="number"
                  step="any"
                  min={0}
                  value={tier.min}
                  onChange={(e) =>
                    updateTier(idx, "min", Number(e.target.value))
                  }
                  className="h-8"
                />
              </TableCell>
              <TableCell className="p-1">
                <Input
                  type="number"
                  step="any"
                  min={0}
                  value={tier.max}
                  onChange={(e) =>
                    updateTier(idx, "max", Number(e.target.value))
                  }
                  className="h-8"
                />
              </TableCell>
              <TableCell className="p-1">
                <Input
                  type="number"
                  step="any"
                  min={0}
                  value={tier.value}
                  onChange={(e) =>
                    updateTier(idx, "value", Number(e.target.value))
                  }
                  className="h-8"
                />
              </TableCell>
              <TableCell className="p-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={tiers.length <= 1}
                  onClick={() => removeTier(idx)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={addTier}
        className="gap-1"
      >
        <Plus className="h-3.5 w-3.5" />
        Add Tier
      </Button>
    </div>
  )
}

// ── Main Dialog Component ────────────────────────────────

export function PricingRuleFormDialog({
  open,
  onOpenChange,
  productId,
  editRule,
  characteristics,
}: PricingRuleFormDialogProps) {
  const createRule = useCreatePricingRule()
  const updateRule = useUpdatePricingRule()
  const isEditing = !!editRule

  // ── Expression-related local state ──────────────────────
  const [amount, setAmount] = useState(0)
  const [percentage, setPercentage] = useState(0)
  const [condition, setCondition] = useState<ConditionNode | null>(null)
  const [adjustmentType, setAdjustmentType] = useState<"fixed" | "percentage">("fixed")
  const [tiers, setTiers] = useState<TierRow[]>([{ min: 0, max: 0, value: 0 }])
  const [formulaStr, setFormulaStr] = useState("")
  const [variablesStr, setVariablesStr] = useState("{}")

  const form = useForm<PricingRuleFormValues>({
    resolver: zodResolver(pricingRuleFormSchema),
    defaultValues: {
      name: "",
      rule_type: "base_price",
      priority: 100,
      is_active: true,
      currency: "USD",
      effective_from: null,
      effective_to: null,
    },
  })

  const ruleType = form.watch("rule_type")

  // ── Sync state on open / editRule change ────────────────
  const resetExpressionState = useCallback(
    (rule: PricingRule | null | undefined) => {
      if (!rule) {
        setAmount(0)
        setPercentage(0)
        setCondition(null)
        setAdjustmentType("fixed")
        setTiers([{ min: 0, max: 0, value: 0 }])
        setFormulaStr("")
        setVariablesStr("{}")
        return
      }

      const expr = rule.expression
      switch (rule.rule_type) {
        case "base_price":
          setAmount(typeof expr.amount === "number" ? expr.amount : 0)
          break
        case "option_surcharge":
          setCondition(parseCondition(expr))
          setAmount(typeof expr.amount === "number" ? expr.amount : 0)
          break
        case "volume_discount":
          setTiers(parseTiers(expr))
          break
        case "conditional":
          setCondition(parseCondition(expr))
          setAdjustmentType(
            expr.adjustment_type === "percentage" ? "percentage" : "fixed",
          )
          setAmount(typeof expr.amount === "number" ? expr.amount : 0)
          break
        case "formula":
          setFormulaStr(typeof expr.formula === "string" ? expr.formula : "")
          setVariablesStr(
            expr.variables && typeof expr.variables === "object"
              ? JSON.stringify(expr.variables, null, 2)
              : "{}",
          )
          break
        case "tiered":
          setTiers(parseTiers(expr))
          break
        case "margin":
          setPercentage(typeof expr.percentage === "number" ? expr.percentage : 0)
          break
      }
    },
    [],
  )

  useEffect(() => {
    if (!open) return
    if (editRule) {
      form.reset({
        name: editRule.name,
        rule_type: editRule.rule_type,
        priority: editRule.priority,
        is_active: editRule.is_active,
        currency: editRule.currency,
        effective_from: editRule.effective_from ?? null,
        effective_to: editRule.effective_to ?? null,
      })
      resetExpressionState(editRule)
    } else {
      form.reset({
        name: "",
        rule_type: "base_price",
        priority: 100,
        is_active: true,
        currency: "USD",
        effective_from: null,
        effective_to: null,
      })
      resetExpressionState(null)
    }
  }, [open, editRule, form, resetExpressionState])

  // ── Build expression from form state ────────────────────

  function buildExpression(type: PricingRuleType): Record<string, unknown> {
    switch (type) {
      case "base_price":
        return { amount }
      case "option_surcharge":
        return {
          condition: condition as Record<string, unknown> | null,
          amount,
        }
      case "volume_discount":
        return {
          tiers: tiers.map((t) => ({
            min: t.min,
            max: t.max,
            discount: t.value,
          })),
          discount_type: "percentage",
        }
      case "conditional":
        return {
          condition: condition as Record<string, unknown> | null,
          adjustment_type: adjustmentType,
          amount,
        }
      case "formula": {
        let parsedVars: Record<string, unknown> = {}
        try {
          parsedVars = JSON.parse(variablesStr)
        } catch {
          // keep empty if invalid
        }
        return { formula: formulaStr, variables: parsedVars }
      }
      case "tiered":
        return {
          tiers: tiers.map((t) => ({
            min: t.min,
            max: t.max,
            amount: t.value,
          })),
        }
      case "margin":
        return { percentage }
    }
  }

  // ── Submit handler ──────────────────────────────────────

  function onSubmit(values: PricingRuleFormValues) {
    const expression = buildExpression(values.rule_type)

    if (isEditing && editRule) {
      updateRule.mutate(
        {
          id: editRule.id,
          data: {
            name: values.name,
            expression,
            priority: values.priority,
            is_active: values.is_active,
            currency: values.currency,
            effective_from: values.effective_from || null,
            effective_to: values.effective_to || null,
          },
        },
        {
          onSuccess: () => onOpenChange(false),
        },
      )
    } else {
      createRule.mutate(
        {
          product_id: productId,
          name: values.name,
          rule_type: values.rule_type,
          expression,
          priority: values.priority,
          is_active: values.is_active,
          currency: values.currency,
          effective_from: values.effective_from || null,
          effective_to: values.effective_to || null,
        },
        {
          onSuccess: () => onOpenChange(false),
        },
      )
    }
  }

  const isPending = isEditing ? updateRule.isPending : createRule.isPending

  // ── Expression section renderer ─────────────────────────

  function renderExpressionFields() {
    switch (ruleType) {
      case "base_price":
        return (
          <div className="space-y-2">
            <label className="text-sm font-medium">Amount</label>
            <Input
              type="number"
              step="0.01"
              min={0}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              placeholder="0.00"
            />
          </div>
        )

      case "option_surcharge":
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Condition</label>
              <ConditionBuilder
                value={condition}
                onChange={setCondition}
                characteristics={characteristics}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Surcharge Amount</label>
              <Input
                type="number"
                step="0.01"
                min={0}
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
                placeholder="0.00"
              />
            </div>
          </div>
        )

      case "volume_discount":
        return (
          <div className="space-y-2">
            <label className="text-sm font-medium">Discount Tiers</label>
            <TiersEditor
              tiers={tiers}
              onChange={setTiers}
              valueLabel="Discount %"
            />
          </div>
        )

      case "conditional":
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Condition</label>
              <ConditionBuilder
                value={condition}
                onChange={setCondition}
                characteristics={characteristics}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Adjustment Type</label>
                <Select
                  value={adjustmentType}
                  onValueChange={(v) =>
                    setAdjustmentType(v as "fixed" | "percentage")
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fixed">Fixed</SelectItem>
                    <SelectItem value="percentage">Percentage</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Amount</label>
                <Input
                  type="number"
                  step="0.01"
                  value={amount}
                  onChange={(e) => setAmount(Number(e.target.value))}
                  placeholder="0.00"
                />
              </div>
            </div>
          </div>
        )

      case "formula":
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Formula</label>
              <Textarea
                value={formulaStr}
                onChange={(e) => setFormulaStr(e.target.value)}
                rows={3}
                placeholder="e.g. base_price * (1 + margin)"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Variables (JSON)</label>
              <Textarea
                value={variablesStr}
                onChange={(e) => setVariablesStr(e.target.value)}
                rows={4}
                placeholder='{ "margin": 0.15 }'
                className="font-mono text-sm"
              />
            </div>
          </div>
        )

      case "tiered":
        return (
          <div className="space-y-2">
            <label className="text-sm font-medium">Price Tiers</label>
            <TiersEditor
              tiers={tiers}
              onChange={setTiers}
              valueLabel="Amount"
            />
          </div>
        )

      case "margin":
        return (
          <div className="space-y-2">
            <label className="text-sm font-medium">Margin Percentage</label>
            <Input
              type="number"
              step="0.01"
              value={percentage}
              onChange={(e) => setPercentage(Number(e.target.value))}
              placeholder="0.00"
            />
          </div>
        )
    }
  }

  // ── Render ──────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>
                {isEditing ? "Edit Pricing Rule" : "New Pricing Rule"}
              </DialogTitle>
              <DialogDescription>
                {isEditing
                  ? "Update the pricing rule configuration."
                  : "Create a new pricing rule for this product."}
              </DialogDescription>
            </DialogHeader>

            <div className="py-4 space-y-6">
              {/* ── Basic Fields ─────────────────────── */}
              <div className="space-y-4">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Name</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          placeholder="e.g. Standard Base Price"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="rule_type"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Rule Type</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={field.value}
                          disabled={isEditing}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Select type..." />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {RULE_TYPES.map((rt) => (
                              <SelectItem key={rt.value} value={rt.value}>
                                {rt.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="priority"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Priority</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            step="1"
                            min={0}
                            {...field}
                            value={field.value ?? 100}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="currency"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Currency</FormLabel>
                        <FormControl>
                          <Input {...field} placeholder="USD" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="is_active"
                    render={({ field }) => (
                      <FormItem className="flex items-center justify-between rounded-lg border p-3 mt-2">
                        <FormLabel className="mb-0">Active</FormLabel>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="effective_from"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Effective From</FormLabel>
                        <FormControl>
                          <Input
                            type="date"
                            {...field}
                            value={field.value ?? ""}
                            onChange={(e) =>
                              field.onChange(e.target.value || null)
                            }
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="effective_to"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Effective To</FormLabel>
                        <FormControl>
                          <Input
                            type="date"
                            {...field}
                            value={field.value ?? ""}
                            onChange={(e) =>
                              field.onChange(e.target.value || null)
                            }
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>

              {/* ── Expression Section ────────────────── */}
              <div className="space-y-3">
                <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
                  Expression
                </h4>
                <div className="rounded-lg border p-4">
                  {renderExpressionFields()}
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending
                  ? "Saving..."
                  : isEditing
                    ? "Update Rule"
                    : "Create Rule"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
