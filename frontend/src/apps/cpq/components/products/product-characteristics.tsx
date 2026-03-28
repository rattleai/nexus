import { useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Plus, Trash2, GripVertical, Pencil } from "lucide-react"
import {
  useCharacteristicAssignments,
  useCharacteristics,
  useAssignCharacteristic,
  useRemoveAssignment,
  useAssignmentsRaw,
  useUpdateAssignment,
} from "@/apps/cpq/hooks/use-characteristics"
import type { CharacteristicAssignment } from "@/apps/cpq/types/configurator"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"

// ── Types ───────────────────────────────────────────────

interface ProductCharacteristicsProps {
  productId: string
}

// ── Char type badge mapping ─────────────────────────────

const charTypeVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  enum: "default",
  numeric: "secondary",
  boolean: "outline",
  text: "destructive",
}

// ── Assignment edit form schema ─────────────────────────

const assignmentEditSchema = z
  .object({
    display_order: z.coerce.number().int(),
    is_required: z.boolean(),
    default_value: z.string().nullable(),
    min_select: z.coerce.number().int().min(0).nullable(),
    max_select: z.coerce.number().int().min(1).nullable(),
  })
  .refine(
    (data) => {
      if (data.min_select != null && data.max_select != null) {
        return data.min_select <= data.max_select
      }
      return true
    },
    { message: "min_select cannot exceed max_select", path: ["min_select"] },
  )

type AssignmentEditFormValues = z.infer<typeof assignmentEditSchema>

// ── Component ───────────────────────────────────────────

export function ProductCharacteristics({ productId }: ProductCharacteristicsProps) {
  const { t } = useTranslation()
  const { data: assignmentsData, isLoading: loadingAssignments } =
    useCharacteristicAssignments(productId)
  const { data: allCharsData, isLoading: loadingChars } = useCharacteristics()
  const { data: rawAssignments } = useAssignmentsRaw(productId)
  const assignCharacteristic = useAssignCharacteristic()
  const removeAssignment = useRemoveAssignment()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedCharId, setSelectedCharId] = useState<string>("")
  const [editingAssignment, setEditingAssignment] = useState<CharacteristicAssignment | null>(null)

  const assignedChars = assignmentsData?.items ?? []
  const allChars = allCharsData?.items ?? []

  // Build a map from characteristic_id to assignment
  const assignmentByCharId = new Map<string, CharacteristicAssignment>()
  if (rawAssignments) {
    for (const a of rawAssignments) {
      assignmentByCharId.set(a.characteristic_id, a)
    }
  }

  // Filter out already-assigned characteristics
  const assignedIds = new Set(assignedChars.map((c) => c.id))
  const availableChars = allChars.filter((c) => !assignedIds.has(c.id))

  function handleAssign() {
    if (!selectedCharId) return
    assignCharacteristic.mutate(
      { product_id: productId, characteristic_id: selectedCharId },
      {
        onSuccess: () => {
          setDialogOpen(false)
          setSelectedCharId("")
        },
      },
    )
  }

  if (loadingAssignments || loadingChars) {
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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("products.characteristics", "Characteristics")}</CardTitle>
          <CardDescription>
            {t(
              "products.characteristicsDescription",
              "Manage the characteristics assigned to this product.",
            )}
          </CardDescription>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="mr-2 h-4 w-4" />
              {t("products.addCharacteristic", "Add Characteristic")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {t("products.assignCharacteristic", "Assign Characteristic")}
              </DialogTitle>
              <DialogDescription>
                {t(
                  "products.assignCharacteristicDescription",
                  "Select a characteristic to assign to this product.",
                )}
              </DialogDescription>
            </DialogHeader>

            <Select value={selectedCharId} onValueChange={setSelectedCharId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={t(
                    "products.selectCharacteristic",
                    "Select characteristic...",
                  )}
                />
              </SelectTrigger>
              <SelectContent>
                {availableChars.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name} ({c.char_type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <DialogFooter>
              <Button
                onClick={handleAssign}
                disabled={!selectedCharId || assignCharacteristic.isPending}
              >
                {assignCharacteristic.isPending
                  ? t("common.assigning", "Assigning...")
                  : t("common.assign", "Assign")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>

      <CardContent>
        {assignedChars.length === 0 ? (
          <EmptyState
            title={t("products.noCharacteristics", "No characteristics assigned")}
            description={t(
              "products.noCharacteristicsDescription",
              "Assign characteristics to define what can be configured on this product.",
            )}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t("common.name", "Name")}</TableHead>
                <TableHead>{t("characteristics.type", "Type")}</TableHead>
                <TableHead>{t("characteristics.required", "Required")}</TableHead>
                <TableHead>{t("characteristics.values", "Values")}</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignedChars.map((char) => {
                const assignment = assignmentByCharId.get(char.id)
                return (
                  <TableRow key={char.id}>
                    <TableCell>
                      <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                    </TableCell>
                    <TableCell className="font-medium">{char.name}</TableCell>
                    <TableCell>
                      <Badge variant={charTypeVariant[char.char_type] ?? "secondary"}>
                        {char.char_type}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          (assignment?.is_required ?? char.is_required)
                            ? "default"
                            : "outline"
                        }
                      >
                        {(assignment?.is_required ?? char.is_required)
                          ? t("common.yes", "Yes")
                          : t("common.no", "No")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {char.char_type === "enum"
                        ? `${char.values?.length ?? 0} values`
                        : char.char_type === "numeric"
                          ? `${char.numeric_min ?? "\u2013"} to ${char.numeric_max ?? "\u2013"}`
                          : "\u2014"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {assignment && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setEditingAssignment(assignment)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() =>
                            removeAssignment.mutate({
                              assignmentId: assignment?.id ?? char.id,
                              productId,
                            })
                          }
                          disabled={removeAssignment.isPending}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <AssignmentEditDialog
        open={editingAssignment !== null}
        onClose={() => setEditingAssignment(null)}
        assignment={editingAssignment}
        productId={productId}
      />
    </Card>
  )
}

// ── Assignment Edit Dialog ──────────────────────────────

function AssignmentEditDialog({
  open,
  onClose,
  assignment,
  productId,
}: {
  open: boolean
  onClose: () => void
  assignment: CharacteristicAssignment | null
  productId: string
}) {
  const { t } = useTranslation()
  const updateAssignment = useUpdateAssignment()

  const form = useForm<AssignmentEditFormValues>({
    resolver: zodResolver(assignmentEditSchema),
    defaultValues: {
      display_order: 0,
      is_required: false,
      default_value: null,
      min_select: null,
      max_select: null,
    },
  })

  // Reset form when dialog opens with assignment data
  useEffect(() => {
    if (open && assignment) {
      form.reset({
        display_order: assignment.display_order,
        is_required: assignment.is_required ?? false,
        default_value: assignment.default_value ?? null,
        min_select: assignment.min_select ?? null,
        max_select: assignment.max_select ?? null,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, assignment])

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      form.reset()
      onClose()
    }
  }

  const onSubmit = async (values: AssignmentEditFormValues) => {
    if (!assignment) return
    try {
      await updateAssignment.mutateAsync({
        assignmentId: assignment.id,
        productId,
        data: {
          display_order: values.display_order,
          is_required: values.is_required,
          default_value: values.default_value || null,
          min_select: values.min_select,
          max_select: values.max_select,
        },
      })
      form.reset()
      onClose()
    } catch {
      toast.error("Failed to update assignment")
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t("products.editAssignment", "Edit Assignment")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "products.editAssignmentDescription",
              "Override characteristic settings for this product assignment.",
            )}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Display order */}
          <div className="space-y-2">
            <Label htmlFor="assign-order">
              {t("characteristics.displayOrder", "Display Order")}
            </Label>
            <Input
              id="assign-order"
              type="number"
              {...form.register("display_order")}
            />
            {form.formState.errors.display_order && (
              <p className="text-sm text-destructive">
                {form.formState.errors.display_order.message}
              </p>
            )}
          </div>

          {/* Is required */}
          <div className="flex items-center justify-between">
            <Label htmlFor="assign-required">
              {t("characteristics.required", "Required")}
            </Label>
            <Switch
              id="assign-required"
              checked={form.watch("is_required")}
              onCheckedChange={(checked) => form.setValue("is_required", checked)}
            />
          </div>

          {/* Default value */}
          <div className="space-y-2">
            <Label htmlFor="assign-default">
              {t("characteristics.defaultValue", "Default Value")}
            </Label>
            <Input
              id="assign-default"
              placeholder={t("common.none", "None")}
              {...form.register("default_value")}
            />
          </div>

          {/* Min / Max select */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="assign-min">
                {t("characteristics.minSelect", "Min Select")}
              </Label>
              <Input
                id="assign-min"
                type="number"
                min={0}
                placeholder={t("common.none", "None")}
                value={form.watch("min_select") ?? ""}
                onChange={(e) =>
                  form.setValue(
                    "min_select",
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              />
              {form.formState.errors.min_select && (
                <p className="text-sm text-destructive">
                  {form.formState.errors.min_select.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="assign-max">
                {t("characteristics.maxSelect", "Max Select")}
              </Label>
              <Input
                id="assign-max"
                type="number"
                min={1}
                placeholder={t("common.none", "None")}
                value={form.watch("max_select") ?? ""}
                onChange={(e) =>
                  form.setValue(
                    "max_select",
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              />
              {form.formState.errors.max_select && (
                <p className="text-sm text-destructive">
                  {form.formState.errors.max_select.message}
                </p>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              {t("common.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={updateAssignment.isPending}>
              {updateAssignment.isPending
                ? t("common.saving", "Saving...")
                : t("common.save", "Save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
