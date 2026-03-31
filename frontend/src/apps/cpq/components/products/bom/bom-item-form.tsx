import { useState, useEffect, useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useCreateBOMItem, useUpdateBOMItem } from "@/apps/cpq/hooks/use-boms"
import { ConditionBuilder, ConditionSummary } from "@/apps/cpq/components/condition-builder"
import type { ConditionNode } from "@/apps/cpq/components/condition-builder"
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
import { ChevronDown, ChevronRight } from "lucide-react"
import type { BOMItem, Characteristic } from "@/apps/cpq/types/configurator"

// ── Zod Schema ──────────────────────────────────────────

const bomItemFormSchema = z.object({
  part_number: z.string().min(1, "Part number is required").max(100),
  part_name: z.string().min(1, "Part name is required").max(255),
  description: z.string().nullable().optional(),
  item_type: z.enum(["component", "sub_assembly", "phantom", "reference"]),
  quantity: z.coerce.number().min(0, "Quantity must be >= 0"),
  unit_of_measure: z.string().min(1).max(20),
  parent_item_id: z.string().nullable().optional(),
  is_optional: z.boolean(),
  unit_cost: z.coerce.number().nullable().optional(),
  lead_time_days: z.coerce.number().int().nullable().optional(),
  sub_product_id: z.string().nullable().optional(),
  selection_condition: z.any().nullable().optional(),
})

type BOMItemFormValues = z.infer<typeof bomItemFormSchema>

// ── Props ───────────────────────────────────────────────

interface BOMItemFormProps {
  bomId: string
  productId: string
  editItem?: BOMItem | null
  parentItemId?: string | null
  allItems: BOMItem[]
  characteristics: Characteristic[]
  onSuccess: () => void
  onCancel: () => void
}

// ── Helpers ─────────────────────────────────────────────

/** Collect all descendant IDs of a given item (to exclude from parent selector). */
function getDescendantIds(itemId: string, items: BOMItem[]): Set<string> {
  const ids = new Set<string>()
  function walk(parentId: string) {
    for (const item of items) {
      if (item.parent_item_id === parentId) {
        ids.add(item.id)
        walk(item.id)
      }
    }
  }
  walk(itemId)
  return ids
}

// ── Component ───────────────────────────────────────────

export function BOMItemForm({
  bomId,
  editItem,
  parentItemId,
  allItems,
  characteristics,
  onSuccess,
  onCancel,
}: BOMItemFormProps) {
  const createItem = useCreateBOMItem()
  const updateItem = useUpdateBOMItem()
  const isEditing = !!editItem

  const [conditionOpen, setConditionOpen] = useState(
    () => editItem?.selection_condition != null,
  )
  const [alwaysIncluded, setAlwaysIncluded] = useState(
    () => editItem?.selection_condition == null,
  )
  const [conditionValue, setConditionValue] = useState<ConditionNode | null>(
    () => (editItem?.selection_condition as ConditionNode | null) ?? null,
  )

  // Items available as parents (exclude self and descendants)
  const parentOptions = useMemo(() => {
    if (!editItem) return allItems
    const excludeIds = getDescendantIds(editItem.id, allItems)
    excludeIds.add(editItem.id)
    return allItems.filter((i) => !excludeIds.has(i.id))
  }, [editItem, allItems])

  const form = useForm<BOMItemFormValues>({
    resolver: zodResolver(bomItemFormSchema),
    defaultValues: {
      part_number: editItem?.part_number ?? "",
      part_name: editItem?.part_name ?? "",
      description: editItem?.description ?? "",
      item_type: editItem?.item_type ?? "component",
      quantity: editItem?.quantity ?? 1,
      unit_of_measure: editItem?.unit_of_measure ?? "EA",
      parent_item_id: editItem?.parent_item_id ?? parentItemId ?? null,
      is_optional: editItem?.is_optional ?? false,
      unit_cost: editItem?.unit_cost ?? null,
      lead_time_days: editItem?.lead_time_days ?? null,
      sub_product_id: editItem?.sub_product_id ?? null,
      selection_condition: editItem?.selection_condition ?? null,
    },
  })

  // Reset form when editItem changes (sheet reuse)
  useEffect(() => {
    form.reset({
      part_number: editItem?.part_number ?? "",
      part_name: editItem?.part_name ?? "",
      description: editItem?.description ?? "",
      item_type: editItem?.item_type ?? "component",
      quantity: editItem?.quantity ?? 1,
      unit_of_measure: editItem?.unit_of_measure ?? "EA",
      parent_item_id: editItem?.parent_item_id ?? parentItemId ?? null,
      is_optional: editItem?.is_optional ?? false,
      unit_cost: editItem?.unit_cost ?? null,
      lead_time_days: editItem?.lead_time_days ?? null,
      sub_product_id: editItem?.sub_product_id ?? null,
      selection_condition: editItem?.selection_condition ?? null,
    })
    setConditionValue((editItem?.selection_condition as ConditionNode | null) ?? null)
    setAlwaysIncluded(editItem?.selection_condition == null)
    setConditionOpen(editItem?.selection_condition != null)
  }, [editItem, parentItemId, form])

  function onSubmit(values: BOMItemFormValues) {
    const selectionCondition = alwaysIncluded ? null : conditionValue

    const payload = {
      part_number: values.part_number,
      part_name: values.part_name,
      description: values.description || null,
      item_type: values.item_type,
      quantity: values.quantity,
      unit_of_measure: values.unit_of_measure,
      parent_item_id: values.parent_item_id || null,
      is_optional: values.is_optional,
      unit_cost: values.unit_cost ?? null,
      lead_time_days: values.lead_time_days ?? null,
      selection_condition: selectionCondition as Record<string, unknown> | null,
    }

    if (isEditing && editItem) {
      updateItem.mutate(
        { bomId, itemId: editItem.id, data: payload },
        { onSuccess },
      )
    } else {
      createItem.mutate(
        { bomId, data: payload },
        { onSuccess },
      )
    }
  }

  const isPending = isEditing ? updateItem.isPending : createItem.isPending

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        {/* ── Part Info ───────────────────────────── */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Part Info
          </h4>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              control={form.control}
              name="part_number"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Part Number</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="e.g. ASM-001" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="part_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Part Name</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="e.g. Main Frame Assembly" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
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
        </div>

        {/* ── Properties ─────────────────────────── */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Properties
          </h4>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              control={form.control}
              name="item_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Item Type</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select type..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="component">Component</SelectItem>
                      <SelectItem value="sub_assembly">Sub-Assembly</SelectItem>
                      <SelectItem value="phantom">Phantom</SelectItem>
                      <SelectItem value="reference">Reference</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-5 gap-2">
              <div className="col-span-3">
                <FormField
                  control={form.control}
                  name="quantity"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Quantity</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="any"
                          min={0}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <div className="col-span-2">
                <FormField
                  control={form.control}
                  name="unit_of_measure"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>UOM</FormLabel>
                      <FormControl>
                        <Input {...field} placeholder="EA" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>

            <FormField
              control={form.control}
              name="unit_cost"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Unit Cost ($)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(
                          e.target.value === "" ? null : Number(e.target.value),
                        )
                      }
                      placeholder="0.00"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="lead_time_days"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Lead Time (days)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step="1"
                      min={0}
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(
                          e.target.value === "" ? null : Number(e.target.value),
                        )
                      }
                      placeholder="0"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        </div>

        {/* ── Hierarchy ──────────────────────────── */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Hierarchy
          </h4>
          <FormField
            control={form.control}
            name="parent_item_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Parent Item</FormLabel>
                <Select
                  onValueChange={(val) =>
                    field.onChange(val === "__root__" ? null : val)
                  }
                  value={field.value ?? "__root__"}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Root level" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="__root__">Root level</SelectItem>
                    {parentOptions.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.part_number} - {item.part_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {/* ── Flags ──────────────────────────────── */}
        <FormField
          control={form.control}
          name="is_optional"
          render={({ field }) => (
            <FormItem className="flex items-center justify-between rounded-lg border p-3">
              <div className="space-y-0.5">
                <FormLabel>Optional Item</FormLabel>
                <p className="text-sm text-muted-foreground">
                  Mark this item as optional in the BOM.
                </p>
              </div>
              <FormControl>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </FormControl>
            </FormItem>
          )}
        />

        {/* ── Selection Condition ────────────────── */}
        <div className="space-y-3">
          <button
            type="button"
            className="flex items-center gap-2 w-full text-left"
            onClick={() => setConditionOpen(!conditionOpen)}
          >
            {conditionOpen ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            <div>
              <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
                Selection Condition
              </h4>
              <p className="text-xs text-muted-foreground">
                Define when this item is included in configured BOMs
              </p>
            </div>
          </button>

          {conditionOpen && (
            <div className="space-y-4 pl-6 border-l-2 border-muted">
              <label className="flex items-center gap-2 cursor-pointer">
                <Switch
                  checked={alwaysIncluded}
                  onCheckedChange={(checked) => {
                    setAlwaysIncluded(checked)
                    if (checked) {
                      setConditionValue(null)
                    }
                  }}
                />
                <span className="text-sm">Always included</span>
              </label>

              {!alwaysIncluded && (
                <div className="space-y-3">
                  <ConditionBuilder
                    value={conditionValue}
                    onChange={setConditionValue}
                    characteristics={characteristics}
                  />
                  {conditionValue && (
                    <div className="rounded-md bg-muted/50 p-3">
                      <p className="text-xs text-muted-foreground mb-1">Summary:</p>
                      <ConditionSummary
                        condition={conditionValue}
                        characteristics={characteristics}
                        className="text-xs"
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Actions ────────────────────────────── */}
        <div className="flex justify-end gap-2 pt-4 border-t">
          <Button variant="outline" type="button" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? "Saving..." : isEditing ? "Update Item" : "Add Item"}
          </Button>
        </div>
      </form>
    </Form>
  )
}
