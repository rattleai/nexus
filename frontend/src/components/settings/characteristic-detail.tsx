import { useState, useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  ArrowLeft,
  Pencil,
  Trash2,
  Plus,
  Check,
  Minus,
  Settings2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import {
  useCharacteristic,
  useCharacteristicGroups,
  useUpdateCharacteristic,
  useDeleteCharacteristic,
  useAddCharacteristicValue,
  useUpdateCharacteristicValue,
  useDeleteCharacteristicValue,
} from "@/apps/cpq/hooks/use-characteristics"
import type { CharacteristicValue, CharType } from "@/apps/cpq/types/configurator"

// ── Type badge styling (matches characteristics-library.tsx) ─────

const typeBadgeVariant: Record<CharType, string> = {
  enum: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  numeric: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
  boolean: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
  text: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400",
}

// ── Value form schema ────────────────────────────────────────────

const valueFormSchema = z.object({
  value: z.string().min(1, "Value code is required").max(200),
  label: z.string().min(1, "Label is required").max(200),
  description: z.string().nullable().optional(),
  display_order: z.coerce.number().default(0),
  is_default: z.boolean().default(false),
  price_adjustment: z.coerce.number().nullable().optional(),
  image_url: z.string().nullable().optional(),
})

type ValueFormValues = z.infer<typeof valueFormSchema>

// ── Main component ───────────────────────────────────────────────

export function CharacteristicDetail({ charId }: { charId: string }) {
  const navigate = useNavigate()
  const { data: characteristic, isLoading, error, refetch } = useCharacteristic(charId)
  const { data: groupsData } = useCharacteristicGroups()
  const deleteCharacteristic = useDeleteCharacteristic()

  const [valueDialogOpen, setValueDialogOpen] = useState(false)
  const [editingValue, setEditingValue] = useState<CharacteristicValue | null>(null)

  const groupName =
    characteristic?.group_id && groupsData?.items
      ? groupsData.items.find((g) => g.id === characteristic.group_id)?.name ?? null
      : null

  const handleDeleteCharacteristic = async () => {
    try {
      await deleteCharacteristic.mutateAsync(charId)
      navigate({ to: "/settings/characteristics" })
    } catch {
      toast.error("Failed to delete characteristic")
    }
  }

  const handleAddValue = () => {
    setEditingValue(null)
    setValueDialogOpen(true)
  }

  const handleEditValue = (value: CharacteristicValue) => {
    setEditingValue(value)
    setValueDialogOpen(true)
  }

  const handleValueDialogClose = () => {
    setValueDialogOpen(false)
    setEditingValue(null)
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Characteristics</span>
        </div>
        <LoadingState variant="skeleton" rows={6} />
      </div>
    )
  }

  // Error state
  if (error || !characteristic) {
    return (
      <div className="space-y-6">
        <Link
          to="/settings/characteristics"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Characteristics
        </Link>
        <ErrorState
          message={
            error instanceof Error
              ? error.message
              : "Failed to load characteristic."
          }
          onRetry={() => refetch()}
        />
      </div>
    )
  }

  const values = characteristic.values ?? []

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        to="/settings/characteristics"
        className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Characteristics
      </Link>

      {/* Page header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
            {characteristic.name}
          </h1>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
              typeBadgeVariant[characteristic.char_type] ?? typeBadgeVariant.text
            }`}
          >
            {characteristic.char_type}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <ConfirmDialog
            title="Delete characteristic"
            description={`Are you sure you want to delete "${characteristic.name}"? This will remove it from all product assignments. This action cannot be undone.`}
            variant="destructive"
            confirmLabel="Delete"
            onConfirm={handleDeleteCharacteristic}
          >
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive">
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </Button>
          </ConfirmDialog>
        </div>
      </div>

      {/* Overview Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Overview</CardTitle>
          <CardDescription>
            Characteristic configuration and metadata
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <OverviewField label="Name" value={characteristic.name} />
            <OverviewField
              label="Slug"
              value={
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono text-muted-foreground">
                  {characteristic.slug}
                </code>
              }
            />
            <OverviewField
              label="Type"
              value={
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    typeBadgeVariant[characteristic.char_type] ?? typeBadgeVariant.text
                  }`}
                >
                  {characteristic.char_type}
                </span>
              }
            />
            <OverviewField label="Group" value={groupName ?? "None"} />
            <OverviewField
              label="Description"
              value={characteristic.description || "No description"}
            />
            <OverviewField
              label="Required"
              value={
                characteristic.is_required ? (
                  <Check className="h-4 w-4 text-primary" />
                ) : (
                  <Minus className="h-4 w-4 text-muted-foreground/40" />
                )
              }
            />
            <OverviewField
              label="Multi-select"
              value={
                characteristic.is_multi_select ? (
                  <Check className="h-4 w-4 text-primary" />
                ) : (
                  <Minus className="h-4 w-4 text-muted-foreground/40" />
                )
              }
            />
            <OverviewField
              label="Display Order"
              value={String(characteristic.display_order)}
            />
            <OverviewField
              label="Default Value"
              value={characteristic.default_value || "None"}
            />

            {/* Numeric-specific fields */}
            {characteristic.char_type === "numeric" && (
              <>
                <OverviewField
                  label="Min"
                  value={characteristic.numeric_min != null ? String(characteristic.numeric_min) : "Not set"}
                />
                <OverviewField
                  label="Max"
                  value={characteristic.numeric_max != null ? String(characteristic.numeric_max) : "Not set"}
                />
                <OverviewField
                  label="Step"
                  value={characteristic.numeric_step != null ? String(characteristic.numeric_step) : "Not set"}
                />
                <OverviewField
                  label="Unit"
                  value={characteristic.unit || "None"}
                />
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Values Card (only for enum type) */}
      {characteristic.char_type === "enum" && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Allowed Values</CardTitle>
              <CardDescription>
                Manage the selectable options for this characteristic
              </CardDescription>
            </div>
            <Button size="sm" onClick={handleAddValue}>
              <Plus className="mr-2 h-4 w-4" />
              Add Value
            </Button>
          </CardHeader>
          <CardContent>
            {values.length === 0 ? (
              <EmptyState
                icon={Settings2}
                title="No values defined"
                description="Add values to define the selectable options for this characteristic."
                action={
                  <Button size="sm" onClick={handleAddValue}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add your first value
                  </Button>
                }
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Value</TableHead>
                    <TableHead>Label</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-center">Order</TableHead>
                    <TableHead className="text-center">Default</TableHead>
                    <TableHead className="text-right">Price Adj.</TableHead>
                    <TableHead className="w-[100px]">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {values
                    .sort((a, b) => a.display_order - b.display_order)
                    .map((val) => (
                      <ValueRow
                        key={val.id}
                        value={val}
                        charId={charId}
                        onEdit={handleEditValue}
                      />
                    ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Value form dialog */}
      <ValueFormDialog
        open={valueDialogOpen}
        onClose={handleValueDialogClose}
        charId={charId}
        value={editingValue}
      />
    </div>
  )
}

// ── Overview field helper ────────────────────────────────────────

function OverviewField({
  label,
  value,
}: {
  label: string
  value: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        {label}
      </p>
      <div className="text-sm text-foreground">{value}</div>
    </div>
  )
}

// ── Value table row ──────────────────────────────────────────────

function ValueRow({
  value,
  charId,
  onEdit,
}: {
  value: CharacteristicValue
  charId: string
  onEdit: (value: CharacteristicValue) => void
}) {
  const deleteValue = useDeleteCharacteristicValue()

  const handleDelete = async () => {
    try {
      await deleteValue.mutateAsync({ charId, valueId: value.id })
    } catch {
      toast.error("Failed to delete value")
    }
  }

  return (
    <TableRow>
      <TableCell>
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono text-muted-foreground">
          {value.value}
        </code>
      </TableCell>
      <TableCell className="font-medium">{value.label}</TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {value.description || "-"}
      </TableCell>
      <TableCell className="text-center tabular-nums">{value.display_order}</TableCell>
      <TableCell className="text-center">
        {value.is_default ? (
          <Check className="h-4 w-4 text-primary mx-auto" />
        ) : (
          <Minus className="h-4 w-4 text-muted-foreground/40 mx-auto" />
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {value.price_adjustment != null ? (
          <span className={value.price_adjustment >= 0 ? "text-foreground" : "text-destructive"}>
            {value.price_adjustment >= 0 ? "+" : ""}
            {value.price_adjustment.toFixed(2)}
          </span>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onEdit(value)}
          >
            <Pencil className="h-4 w-4" />
            <span className="sr-only">Edit value</span>
          </Button>
          <ConfirmDialog
            title="Delete value"
            description={`Are you sure you want to delete the value "${value.label}"? This action cannot be undone.`}
            variant="destructive"
            confirmLabel="Delete"
            onConfirm={handleDelete}
          >
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-destructive hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
              <span className="sr-only">Delete value</span>
            </Button>
          </ConfirmDialog>
        </div>
      </TableCell>
    </TableRow>
  )
}

// ── Value form dialog ────────────────────────────────────────────

function ValueFormDialog({
  open,
  onClose,
  charId,
  value,
}: {
  open: boolean
  onClose: () => void
  charId: string
  value: CharacteristicValue | null
}) {
  const isEditing = value !== null
  const addValue = useAddCharacteristicValue()
  const updateValue = useUpdateCharacteristicValue()

  const form = useForm<ValueFormValues>({
    resolver: zodResolver(valueFormSchema),
    defaultValues: {
      value: "",
      label: "",
      description: "",
      display_order: 0,
      is_default: false,
      price_adjustment: null,
      image_url: "",
    },
  })

  // Reset form when dialog opens with new data
  useEffect(() => {
    if (open && value) {
      form.reset({
        value: value.value,
        label: value.label,
        description: value.description ?? "",
        display_order: value.display_order,
        is_default: value.is_default,
        price_adjustment: value.price_adjustment,
        image_url: value.image_url ?? "",
      })
    } else if (open && !value) {
      form.reset({
        value: "",
        label: "",
        description: "",
        display_order: 0,
        is_default: false,
        price_adjustment: null,
        image_url: "",
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, value])

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      form.reset()
      onClose()
    }
  }

  const onSubmit = async (values: ValueFormValues) => {
    try {
      if (isEditing && value) {
        await updateValue.mutateAsync({
          charId,
          valueId: value.id,
          data: {
            label: values.label,
            description: values.description || null,
            display_order: values.display_order,
            is_default: values.is_default,
            price_adjustment: values.price_adjustment ?? null,
            image_url: values.image_url || null,
          },
        })
      } else {
        await addValue.mutateAsync({
          charId,
          data: {
            value: values.value,
            label: values.label,
            description: values.description || null,
            display_order: values.display_order,
            is_default: values.is_default,
            price_adjustment: values.price_adjustment ?? null,
            image_url: values.image_url || null,
          },
        })
      }
      form.reset()
      onClose()
    } catch {
      toast.error(`Failed to ${isEditing ? "update" : "add"} value`)
    }
  }

  const isPending = addValue.isPending || updateValue.isPending

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Value" : "Add Value"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the value details for this characteristic."
              : "Add a new selectable value to this characteristic."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Value code */}
          <div className="space-y-2">
            <Label htmlFor="val-value">Value (code)</Label>
            <Input
              id="val-value"
              placeholder="e.g. red, xl, 220v"
              disabled={isEditing}
              {...form.register("value")}
            />
            {form.formState.errors.value && (
              <p className="text-sm text-destructive">
                {form.formState.errors.value.message}
              </p>
            )}
            {isEditing && (
              <p className="text-xs text-muted-foreground">
                Value code cannot be changed after creation.
              </p>
            )}
          </div>

          {/* Label */}
          <div className="space-y-2">
            <Label htmlFor="val-label">Label (display name)</Label>
            <Input
              id="val-label"
              placeholder="e.g. Red, Extra Large, 220 Volts"
              {...form.register("label")}
            />
            {form.formState.errors.label && (
              <p className="text-sm text-destructive">
                {form.formState.errors.label.message}
              </p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="val-description">Description</Label>
            <Textarea
              id="val-description"
              placeholder="Optional description of this value..."
              rows={2}
              {...form.register("description")}
            />
          </div>

          {/* Display order & is_default */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="val-order">Display Order</Label>
              <Input
                id="val-order"
                type="number"
                placeholder="0"
                {...form.register("display_order")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="val-default" className="text-sm">
                Default
              </Label>
              <div className="flex items-center gap-2 pt-1">
                <Switch
                  id="val-default"
                  checked={form.watch("is_default")}
                  onCheckedChange={(checked) => form.setValue("is_default", checked)}
                />
                <span className="text-xs text-muted-foreground">
                  Pre-selected value
                </span>
              </div>
            </div>
          </div>

          {/* Price adjustment */}
          <div className="space-y-2">
            <Label htmlFor="val-price">Price Adjustment</Label>
            <Input
              id="val-price"
              type="number"
              step="0.01"
              placeholder="0.00"
              {...form.register("price_adjustment")}
            />
            <p className="text-xs text-muted-foreground">
              Amount added or subtracted from the base price when this value is selected.
            </p>
          </div>

          {/* Image URL */}
          <div className="space-y-2">
            <Label htmlFor="val-image">Image URL</Label>
            <Input
              id="val-image"
              placeholder="https://..."
              {...form.register("image_url")}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                form.reset()
                onClose()
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? "Saving..." : isEditing ? "Update" : "Add Value"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
