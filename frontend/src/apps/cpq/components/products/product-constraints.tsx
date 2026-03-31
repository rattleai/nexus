import { useState, useEffect, useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import {
  ShieldCheck,
  AlertTriangle,
  Plus,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronRight,
} from "lucide-react"
import {
  useConstraintRules,
  useConstraintGroups,
  useCreateConstraintRule,
  useUpdateConstraintRule,
  useDeleteConstraintRule,
  useCreateConstraintGroup,
  useUpdateConstraintGroup,
  useDeleteConstraintGroup,
  useVariantTables,
} from "@/apps/cpq/hooks/use-constraints"
import { useCharacteristicAssignments } from "@/apps/cpq/hooks/use-characteristics"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ProductVariantTables } from "@/apps/cpq/components/products/product-variant-tables"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { ConditionBuilder, ConditionSummary } from "@/apps/cpq/components/condition-builder"
import type { ConditionNode } from "@/apps/cpq/components/condition-builder"
import { MultiSelect } from "@/components/multi-select"
import type {
  ConstraintRule,
  ConstraintGroup,
  ConstraintType,
  Characteristic,
} from "@/apps/cpq/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductConstraintsProps {
  productId: string
}

// ── Constraint type badge colors ────────────────────────

const constraintTypeBadgeClass: Record<ConstraintType, string> = {
  requires: "bg-blue-600 hover:bg-blue-600 text-white",
  excludes: "bg-red-600 hover:bg-red-600 text-white",
  selection_condition: "bg-amber-600 hover:bg-amber-600 text-white",
  default_value: "bg-emerald-600 hover:bg-emerald-600 text-white",
  formula: "bg-purple-600 hover:bg-purple-600 text-white",
  table: "bg-cyan-600 hover:bg-cyan-600 text-white",
}

const constraintTypeLabels: Record<ConstraintType, string> = {
  requires: "Requires",
  excludes: "Excludes",
  selection_condition: "Condition",
  default_value: "Default",
  formula: "Formula",
  table: "Table",
}

const CONSTRAINT_TYPES: ConstraintType[] = [
  "requires",
  "excludes",
  "selection_condition",
  "default_value",
  "formula",
  "table",
]

// ── Group Form Schema ───────────────────────────────────

const groupFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable().optional(),
  is_active: z.boolean(),
})

type GroupFormValues = z.infer<typeof groupFormSchema>

// ── Rule Form Schema ────────────────────────────────────

const ruleFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable().optional(),
  constraint_type: z.enum([
    "requires",
    "excludes",
    "selection_condition",
    "default_value",
    "formula",
    "table",
  ]),
  group_id: z.string().nullable().optional(),
  priority: z.coerce.number().int().min(0).default(100),
  is_active: z.boolean(),
  effective_from: z.string().nullable().optional(),
  effective_to: z.string().nullable().optional(),
})

type RuleFormValues = z.infer<typeof ruleFormSchema>

// ── Constraint Group Form Dialog ────────────────────────

function ConstraintGroupFormDialog({
  productId,
  group,
  open,
  onOpenChange,
}: {
  productId: string
  group?: ConstraintGroup | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const createGroup = useCreateConstraintGroup()
  const updateGroup = useUpdateConstraintGroup()
  const isEditing = !!group

  const form = useForm<GroupFormValues>({
    resolver: zodResolver(groupFormSchema),
    defaultValues: {
      name: group?.name ?? "",
      description: group?.description ?? "",
      is_active: group?.is_active ?? true,
    },
  })

  useEffect(() => {
    if (open) {
      form.reset({
        name: group?.name ?? "",
        description: group?.description ?? "",
        is_active: group?.is_active ?? true,
      })
    }
  }, [open, group, form])

  function onSubmit(values: GroupFormValues) {
    const payload = {
      name: values.name,
      description: values.description || null,
      is_active: values.is_active,
    }

    if (isEditing && group) {
      updateGroup.mutate(
        { id: group.id, data: payload },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    } else {
      createGroup.mutate(
        { product_id: productId, ...payload },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    }
  }

  const isPending = isEditing ? updateGroup.isPending : createGroup.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Group" : "Create Constraint Group"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the constraint group details."
              : "Create a new constraint group to organize rules."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="e.g. Engine Constraints" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      value={field.value ?? ""}
                      rows={3}
                      placeholder="Optional description..."
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <FormLabel>Active</FormLabel>
                    <p className="text-sm text-muted-foreground">
                      Enable or disable all rules in this group.
                    </p>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Saving..." : isEditing ? "Update" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

// ── Expression Editor (adapts by constraint type) ───────

function ExpressionEditor({
  constraintType,
  ifCondition,
  onIfConditionChange,
  thenChar,
  onThenCharChange,
  thenValues,
  onThenValuesChange,
  formulaText,
  onFormulaTextChange,
  formulaVars,
  onFormulaVarsChange,
  tableId,
  onTableIdChange,
  characteristics,
  variantTableOptions,
}: {
  constraintType: ConstraintType
  ifCondition: ConditionNode | null
  onIfConditionChange: (v: ConditionNode | null) => void
  thenChar: string
  onThenCharChange: (v: string) => void
  thenValues: string[]
  onThenValuesChange: (v: string[]) => void
  formulaText: string
  onFormulaTextChange: (v: string) => void
  formulaVars: string
  onFormulaVarsChange: (v: string) => void
  tableId: string
  onTableIdChange: (v: string) => void
  characteristics: Characteristic[]
  variantTableOptions: { value: string; label: string }[]
}) {
  const selectedChar = characteristics.find((c) => c.slug === thenChar)
  const charValueOptions = useMemo(
    () =>
      selectedChar?.values?.map((v) => ({ value: v.value, label: v.label })) ?? [],
    [selectedChar],
  )

  if (constraintType === "requires" || constraintType === "excludes") {
    const thenLabel =
      constraintType === "requires" ? "must have values" : "cannot have values"

    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium">IF (Trigger Condition)</label>
          <div className="rounded-lg border p-3">
            <ConditionBuilder
              value={ifCondition}
              onChange={onIfConditionChange}
              characteristics={characteristics}
            />
          </div>
        </div>
        <Separator />
        <div className="space-y-2">
          <label className="text-sm font-medium">
            THEN &mdash; Characteristic {thenLabel}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Characteristic</label>
              <Select value={thenChar} onValueChange={onThenCharChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select characteristic..." />
                </SelectTrigger>
                <SelectContent>
                  {characteristics.map((c) => (
                    <SelectItem key={c.slug} value={c.slug}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Values</label>
              <MultiSelect
                options={charValueOptions}
                selected={thenValues}
                onChange={onThenValuesChange}
                placeholder="Select values..."
              />
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (constraintType === "selection_condition") {
    return (
      <div className="space-y-2">
        <label className="text-sm font-medium">Selection Condition</label>
        <div className="rounded-lg border p-3">
          <ConditionBuilder
            value={ifCondition}
            onChange={onIfConditionChange}
            characteristics={characteristics}
          />
        </div>
      </div>
    )
  }

  if (constraintType === "default_value") {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium">IF (Trigger Condition)</label>
          <div className="rounded-lg border p-3">
            <ConditionBuilder
              value={ifCondition}
              onChange={onIfConditionChange}
              characteristics={characteristics}
            />
          </div>
        </div>
        <Separator />
        <div className="space-y-2">
          <label className="text-sm font-medium">THEN &mdash; Set Default Value</label>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Characteristic</label>
              <Select value={thenChar} onValueChange={onThenCharChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select characteristic..." />
                </SelectTrigger>
                <SelectContent>
                  {characteristics.map((c) => (
                    <SelectItem key={c.slug} value={c.slug}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Default Value</label>
              <Select
                value={thenValues[0] ?? ""}
                onValueChange={(v) => onThenValuesChange([v])}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select value..." />
                </SelectTrigger>
                <SelectContent>
                  {charValueOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (constraintType === "formula") {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium">Formula Expression</label>
          <Textarea
            value={formulaText}
            onChange={(e) => onFormulaTextChange(e.target.value)}
            rows={4}
            placeholder='e.g. price = base_price * (1 + markup)'
            className="font-mono text-sm"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">Variables (JSON)</label>
          <Textarea
            value={formulaVars}
            onChange={(e) => onFormulaVarsChange(e.target.value)}
            rows={4}
            placeholder='{ "base_price": "characteristic_slug", "markup": 0.15 }'
            className="font-mono text-sm"
          />
        </div>
      </div>
    )
  }

  if (constraintType === "table") {
    return (
      <div className="space-y-2">
        <label className="text-sm font-medium">Variant Table</label>
        <Select value={tableId} onValueChange={onTableIdChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select variant table..." />
          </SelectTrigger>
          <SelectContent>
            {variantTableOptions.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  return null
}

// ── Helper: parse expression into parts ─────────────────

function parseExpression(
  expression: Record<string, unknown>,
  constraintType: ConstraintType,
) {
  const result = {
    ifCondition: null as ConditionNode | null,
    thenChar: "",
    thenValues: [] as string[],
    formulaText: "",
    formulaVars: "",
    tableId: "",
  }

  if (constraintType === "requires" || constraintType === "excludes") {
    if (expression.if) {
      result.ifCondition = expression.if as ConditionNode
    }
    if (expression.then && typeof expression.then === "object") {
      const then = expression.then as Record<string, unknown>
      result.thenChar = (then.char as string) ?? ""
      const val = then.value
      if (Array.isArray(val)) {
        result.thenValues = val as string[]
      } else if (typeof val === "string") {
        result.thenValues = [val]
      }
    }
  } else if (constraintType === "selection_condition") {
    // The entire expression (minus the type wrapper) is the condition
    if (expression.condition) {
      result.ifCondition = expression.condition as ConditionNode
    } else {
      // Try using expression directly if it looks like a condition
      const { type: _type, ...rest } = expression
      if (Object.keys(rest).length > 0) {
        result.ifCondition = rest as unknown as ConditionNode
      }
    }
  } else if (constraintType === "default_value") {
    if (expression.if) {
      result.ifCondition = expression.if as ConditionNode
    }
    if (expression.then && typeof expression.then === "object") {
      const then = expression.then as Record<string, unknown>
      result.thenChar = (then.char as string) ?? ""
      const val = then.value
      if (typeof val === "string") {
        result.thenValues = [val]
      }
    }
  } else if (constraintType === "formula") {
    result.formulaText = (expression.formula as string) ?? ""
    if (expression.variables) {
      result.formulaVars = JSON.stringify(expression.variables, null, 2)
    }
  } else if (constraintType === "table") {
    result.tableId = (expression.table_id as string) ?? ""
  }

  return result
}

// ── Helper: compose expression from parts ───────────────

function composeExpression(
  constraintType: ConstraintType,
  ifCondition: ConditionNode | null,
  thenChar: string,
  thenValues: string[],
  formulaText: string,
  formulaVars: string,
  tableId: string,
): Record<string, unknown> {
  if (constraintType === "requires" || constraintType === "excludes") {
    return {
      type: constraintType,
      if: ifCondition ?? {},
      then: {
        char: thenChar,
        op: "in",
        value: thenValues,
      },
    }
  }

  if (constraintType === "selection_condition") {
    return {
      type: "selection_condition",
      condition: ifCondition ?? {},
    }
  }

  if (constraintType === "default_value") {
    return {
      type: "default_value",
      if: ifCondition ?? {},
      then: {
        char: thenChar,
        value: thenValues[0] ?? "",
      },
    }
  }

  if (constraintType === "formula") {
    let vars: Record<string, unknown> = {}
    try {
      vars = JSON.parse(formulaVars || "{}")
    } catch {
      // keep empty
    }
    return {
      type: "formula",
      formula: formulaText,
      variables: vars,
    }
  }

  if (constraintType === "table") {
    return {
      type: "table",
      table_id: tableId,
    }
  }

  return {}
}

// ── Constraint Rule Form Dialog ─────────────────────────

function ConstraintRuleFormDialog({
  productId,
  rule,
  open,
  onOpenChange,
  groups,
  characteristics,
  variantTableOptions,
}: {
  productId: string
  rule?: ConstraintRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
  groups: ConstraintGroup[]
  characteristics: Characteristic[]
  variantTableOptions: { value: string; label: string }[]
}) {
  const createRule = useCreateConstraintRule()
  const updateRule = useUpdateConstraintRule()
  const isEditing = !!rule

  const form = useForm<RuleFormValues>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: {
      name: rule?.name ?? "",
      description: rule?.description ?? "",
      constraint_type: rule?.constraint_type ?? "requires",
      group_id: rule?.group_id ?? null,
      priority: rule?.priority ?? 100,
      is_active: rule?.is_active ?? true,
      effective_from: rule?.effective_from ?? "",
      effective_to: rule?.effective_to ?? "",
    },
  })

  const watchType = form.watch("constraint_type") as ConstraintType

  // Expression editor state
  const [ifCondition, setIfCondition] = useState<ConditionNode | null>(null)
  const [thenChar, setThenChar] = useState("")
  const [thenValues, setThenValues] = useState<string[]>([])
  const [formulaText, setFormulaText] = useState("")
  const [formulaVars, setFormulaVars] = useState("")
  const [tableId, setTableId] = useState("")

  useEffect(() => {
    if (open) {
      form.reset({
        name: rule?.name ?? "",
        description: rule?.description ?? "",
        constraint_type: rule?.constraint_type ?? "requires",
        group_id: rule?.group_id ?? null,
        priority: rule?.priority ?? 100,
        is_active: rule?.is_active ?? true,
        effective_from: rule?.effective_from ?? "",
        effective_to: rule?.effective_to ?? "",
      })

      // Parse existing expression
      if (rule?.expression) {
        const parsed = parseExpression(
          rule.expression,
          rule.constraint_type,
        )
        setIfCondition(parsed.ifCondition)
        setThenChar(parsed.thenChar)
        setThenValues(parsed.thenValues)
        setFormulaText(parsed.formulaText)
        setFormulaVars(parsed.formulaVars)
        setTableId(parsed.tableId)
      } else {
        setIfCondition(null)
        setThenChar("")
        setThenValues([])
        setFormulaText("")
        setFormulaVars("")
        setTableId("")
      }
    }
  }, [open, rule, form])

  function onSubmit(values: RuleFormValues) {
    const expression = composeExpression(
      values.constraint_type as ConstraintType,
      ifCondition,
      thenChar,
      thenValues,
      formulaText,
      formulaVars,
      tableId,
    )

    if (isEditing && rule) {
      updateRule.mutate(
        {
          id: rule.id,
          data: {
            name: values.name,
            description: values.description || null,
            group_id: values.group_id || null,
            expression,
            priority: values.priority,
            is_active: values.is_active,
            effective_from: values.effective_from || null,
            effective_to: values.effective_to || null,
          },
        },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    } else {
      createRule.mutate(
        {
          product_id: productId,
          name: values.name,
          description: values.description || null,
          constraint_type: values.constraint_type as ConstraintType,
          group_id: values.group_id || null,
          expression,
          priority: values.priority,
          is_active: values.is_active,
          effective_from: values.effective_from || null,
          effective_to: values.effective_to || null,
        },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    }
  }

  const isPending = isEditing ? updateRule.isPending : createRule.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Constraint Rule" : "Create Constraint Rule"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the constraint rule configuration."
              : "Define a new constraint rule for this product."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Row 1: Name + Type */}
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="e.g. V8 requires auto transmission" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="constraint_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Constraint Type</FormLabel>
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
                        {CONSTRAINT_TYPES.map((ct) => (
                          <SelectItem key={ct} value={ct}>
                            {constraintTypeLabels[ct]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Description */}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      value={field.value ?? ""}
                      rows={2}
                      placeholder="Optional description..."
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Row 2: Group + Priority */}
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="group_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Group</FormLabel>
                    <Select
                      onValueChange={(v) => field.onChange(v === "__ungrouped__" ? null : v)}
                      value={field.value ?? "__ungrouped__"}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select group..." />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="__ungrouped__">Ungrouped</SelectItem>
                        {groups.map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.name}
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
                      <Input type="number" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Effective dates */}
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="effective_from"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Effective From</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} value={field.value ?? ""} />
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
                      <Input type="date" {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Active toggle */}
            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <FormLabel>Active</FormLabel>
                    <p className="text-sm text-muted-foreground">
                      Enable or disable this constraint rule.
                    </p>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />

            {/* Expression Editor */}
            <Separator />
            <div className="space-y-2">
              <h4 className="text-sm font-semibold">Expression</h4>
              <ExpressionEditor
                constraintType={watchType as ConstraintType}
                ifCondition={ifCondition}
                onIfConditionChange={setIfCondition}
                thenChar={thenChar}
                onThenCharChange={setThenChar}
                thenValues={thenValues}
                onThenValuesChange={setThenValues}
                formulaText={formulaText}
                onFormulaTextChange={setFormulaText}
                formulaVars={formulaVars}
                onFormulaVarsChange={setFormulaVars}
                tableId={tableId}
                onTableIdChange={setTableId}
                characteristics={characteristics}
                variantTableOptions={variantTableOptions}
              />
            </div>

            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Saving..." : isEditing ? "Update" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

// ── Constraint Rule Row ─────────────────────────────────

function ConstraintRuleRow({
  rule,
  onToggle,
  onEdit,
  onDelete,
  isPending,
  characteristics,
}: {
  rule: ConstraintRule
  onToggle: (rule: ConstraintRule) => void
  onEdit: (rule: ConstraintRule) => void
  onDelete: (rule: ConstraintRule) => void
  isPending: boolean
  characteristics: Characteristic[]
}) {
  // Build a short expression summary
  const expressionSummary = useMemo(() => {
    const expr = rule.expression
    if (!expr || Object.keys(expr).length === 0) return null

    if (
      (rule.constraint_type === "requires" || rule.constraint_type === "excludes") &&
      expr.if &&
      expr.then
    ) {
      const thenObj = expr.then as Record<string, unknown>
      const thenChar = characteristics.find((c) => c.slug === thenObj.char)
      const verb = rule.constraint_type === "requires" ? "requires" : "excludes"
      const vals = Array.isArray(thenObj.value) ? thenObj.value.join(", ") : String(thenObj.value ?? "")
      return (
        <span className="text-xs text-muted-foreground">
          <ConditionSummary
            condition={expr.if as ConditionNode}
            characteristics={characteristics}
            className="text-xs"
          />
          {" "}
          <span className="font-medium">{verb}</span>{" "}
          {thenChar?.name ?? thenObj.char} = [{vals}]
        </span>
      )
    }

    if (rule.constraint_type === "selection_condition" && expr.condition) {
      return (
        <ConditionSummary
          condition={expr.condition as ConditionNode}
          characteristics={characteristics}
          className="text-xs"
        />
      )
    }

    if (rule.constraint_type === "formula" && expr.formula) {
      return (
        <span className="text-xs text-muted-foreground font-mono truncate max-w-[300px] inline-block">
          {String(expr.formula)}
        </span>
      )
    }

    if (rule.constraint_type === "table" && expr.table_id) {
      return (
        <span className="text-xs text-muted-foreground">
          Table: {String(expr.table_id).substring(0, 8)}...
        </span>
      )
    }

    return null
  }, [rule, characteristics])

  return (
    <div className="flex items-center justify-between rounded-lg border p-3 gap-3">
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">{rule.name}</span>
          <Badge className={constraintTypeBadgeClass[rule.constraint_type]}>
            {constraintTypeLabels[rule.constraint_type]}
          </Badge>
          <span className="text-xs text-muted-foreground">
            Priority: {rule.priority}
          </span>
          {!rule.is_active && (
            <Badge variant="outline" className="text-xs">
              <AlertTriangle className="mr-1 h-3 w-3" />
              Inactive
            </Badge>
          )}
        </div>
        {rule.description && (
          <p className="text-xs text-muted-foreground">{rule.description}</p>
        )}
        {expressionSummary && <div className="mt-0.5">{expressionSummary}</div>}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <Switch
          checked={rule.is_active}
          onCheckedChange={() => onToggle(rule)}
          disabled={isPending}
        />
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => onEdit(rule)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <ConfirmDialog
          title="Delete Constraint Rule"
          description={`Are you sure you want to delete "${rule.name}"? This action cannot be undone.`}
          confirmLabel="Delete"
          variant="destructive"
          onConfirm={() => onDelete(rule)}
        >
          <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </ConfirmDialog>
      </div>
    </div>
  )
}

// ── Collapsible Group Card ──────────────────────────────

function GroupCard({
  group,
  rules,
  onEditGroup,
  onDeleteGroup,
  onToggleGroupActive,
  onToggleRule,
  onEditRule,
  onDeleteRule,
  updateRulePending,
  characteristics,
}: {
  group: ConstraintGroup
  rules: ConstraintRule[]
  onEditGroup: (g: ConstraintGroup) => void
  onDeleteGroup: (g: ConstraintGroup) => void
  onToggleGroupActive: (g: ConstraintGroup) => void
  onToggleRule: (r: ConstraintRule) => void
  onEditRule: (r: ConstraintRule) => void
  onDeleteRule: (r: ConstraintRule) => void
  updateRulePending: boolean
  characteristics: Characteristic[]
}) {
  const [expanded, setExpanded] = useState(true)

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div
            className="flex items-center gap-2 cursor-pointer select-none flex-1"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            <div className="space-y-0.5">
              <CardTitle className="text-base">{group.name}</CardTitle>
              {group.description && (
                <p className="text-xs text-muted-foreground">{group.description}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {!group.is_active && (
              <Badge variant="outline">
                <AlertTriangle className="mr-1 h-3 w-3" />
                Inactive
              </Badge>
            )}
            <Switch
              checked={group.is_active}
              onCheckedChange={() => onToggleGroupActive(group)}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => onEditGroup(group)}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <ConfirmDialog
              title="Delete Constraint Group"
              description={`Are you sure you want to delete group "${group.name}"? Rules in this group will become ungrouped.`}
              confirmLabel="Delete"
              variant="destructive"
              onConfirm={() => onDeleteGroup(group)}
            >
              <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </ConfirmDialog>
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-2 pt-0">
          {rules.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-4 text-center">
              No rules in this group
            </p>
          ) : (
            rules
              .sort((a, b) => a.priority - b.priority)
              .map((rule) => (
                <ConstraintRuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={onToggleRule}
                  onEdit={onEditRule}
                  onDelete={onDeleteRule}
                  isPending={updateRulePending}
                  characteristics={characteristics}
                />
              ))
          )}
        </CardContent>
      )}
    </Card>
  )
}

// ── Main Component ──────────────────────────────────────

export function ProductConstraints({ productId }: ProductConstraintsProps) {
  const { data: rulesData, isLoading: loadingRules } = useConstraintRules({
    product_id: productId,
  })
  const { data: groupsData, isLoading: loadingGroups } = useConstraintGroups(productId)
  const { data: charsData } = useCharacteristicAssignments(productId)
  const { data: tablesData } = useVariantTables(productId)

  const updateRule = useUpdateConstraintRule()
  const deleteRule = useDeleteConstraintRule()
  const updateGroup = useUpdateConstraintGroup()
  const deleteGroup = useDeleteConstraintGroup()

  // Dialog state
  const [groupDialogOpen, setGroupDialogOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<ConstraintGroup | null>(null)
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<ConstraintRule | null>(null)

  const rules = rulesData?.items ?? []
  const groups = groupsData?.items ?? []
  const characteristics = charsData?.items ?? []
  const variantTableOptions = useMemo(
    () =>
      (tablesData?.items ?? []).map((t) => ({ value: t.id, label: t.name })),
    [tablesData],
  )

  // Handlers
  function handleToggleRuleActive(rule: ConstraintRule) {
    updateRule.mutate({ id: rule.id, data: { is_active: !rule.is_active } })
  }

  function handleEditRule(rule: ConstraintRule) {
    setEditingRule(rule)
    setRuleDialogOpen(true)
  }

  function handleDeleteRule(rule: ConstraintRule) {
    deleteRule.mutate(rule.id)
  }

  function handleEditGroup(group: ConstraintGroup) {
    setEditingGroup(group)
    setGroupDialogOpen(true)
  }

  function handleDeleteGroup(group: ConstraintGroup) {
    deleteGroup.mutate(group.id)
  }

  function handleToggleGroupActive(group: ConstraintGroup) {
    updateGroup.mutate({
      id: group.id,
      data: { is_active: !group.is_active },
    })
  }

  function handleNewGroup() {
    setEditingGroup(null)
    setGroupDialogOpen(true)
  }

  function handleNewRule() {
    setEditingRule(null)
    setRuleDialogOpen(true)
  }

  // Group rules by constraint group (computed regardless of loading)
  const groupMap = new Map(groups.map((g) => [g.id, g]))
  const ungroupedRules = rules.filter((r) => !r.group_id)
  const groupedRulesMap = new Map<string, ConstraintRule[]>()

  for (const rule of rules) {
    if (rule.group_id) {
      const existing = groupedRulesMap.get(rule.group_id) ?? []
      existing.push(rule)
      groupedRulesMap.set(rule.group_id, existing)
    }
  }

  // Groups that have no rules yet should still appear
  for (const group of groups) {
    if (!groupedRulesMap.has(group.id)) {
      groupedRulesMap.set(group.id, [])
    }
  }

  // Rules tab content
  const rulesContent = loadingRules || loadingGroups ? (
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
  ) : rules.length === 0 && groups.length === 0 ? (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Constraints</CardTitle>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleNewGroup}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              New Group
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <EmptyState
          icon={ShieldCheck}
          title="No constraint rules yet"
          description="Add constraint rules to enforce configuration logic for this product."
          action={
            <Button onClick={handleNewRule}>
              <Plus className="mr-1.5 h-4 w-4" />
              Create Rule
            </Button>
          }
        />
      </CardContent>
    </Card>
  ) : (
    <div className="space-y-4">
      {/* Header actions */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" />
          Constraints
        </h3>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleNewGroup}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Group
          </Button>
          <Button size="sm" onClick={handleNewRule}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Rule
          </Button>
        </div>
      </div>

      {/* Grouped rules */}
      {Array.from(groupedRulesMap.entries()).map(([groupId, groupRules]) => {
        const group = groupMap.get(groupId)
        if (!group) return null
        return (
          <GroupCard
            key={groupId}
            group={group}
            rules={groupRules}
            onEditGroup={handleEditGroup}
            onDeleteGroup={handleDeleteGroup}
            onToggleGroupActive={handleToggleGroupActive}
            onToggleRule={handleToggleRuleActive}
            onEditRule={handleEditRule}
            onDeleteRule={handleDeleteRule}
            updateRulePending={updateRule.isPending}
            characteristics={characteristics}
          />
        )
      })}

      {/* Ungrouped rules */}
      {ungroupedRules.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Ungrouped Rules</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {ungroupedRules
              .sort((a, b) => a.priority - b.priority)
              .map((rule) => (
                <ConstraintRuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={handleToggleRuleActive}
                  onEdit={handleEditRule}
                  onDelete={handleDeleteRule}
                  isPending={updateRule.isPending}
                  characteristics={characteristics}
                />
              ))}
          </CardContent>
        </Card>
      )}
    </div>
  )

  return (
    <>
      <Tabs defaultValue="rules">
        <TabsList>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="variant-tables">Variant Tables</TabsTrigger>
        </TabsList>

        <TabsContent value="rules">
          {rulesContent}
        </TabsContent>

        <TabsContent value="variant-tables">
          <ProductVariantTables productId={productId} />
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <ConstraintGroupFormDialog
        productId={productId}
        group={editingGroup}
        open={groupDialogOpen}
        onOpenChange={setGroupDialogOpen}
      />
      <ConstraintRuleFormDialog
        productId={productId}
        rule={editingRule}
        open={ruleDialogOpen}
        onOpenChange={setRuleDialogOpen}
        groups={groups}
        characteristics={characteristics}
        variantTableOptions={variantTableOptions}
      />
    </>
  )
}
