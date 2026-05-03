import { useState, useMemo, useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Link } from "@tanstack/react-router"
import {
  Plus,
  Search,
  Pencil,
  Trash2,
  MoreHorizontal,
  BookOpen,
  Check,
  Minus,
  Layers,
  Eye,
  ListChecks,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { CharacteristicGroupsPanel } from "@/apps/cpq/components/settings/characteristic-groups-panel"
import {
  useCharacteristics,
  useCharacteristicGroups,
  useCreateCharacteristic,
  useUpdateCharacteristic,
  useDeleteCharacteristic,
} from "@/apps/cpq/hooks/use-characteristics"
import type { Characteristic, CharType } from "@/apps/cpq/types/configurator"

// ── Slug helper ──────────────────────────────────────────

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
}

// ── Type badge styling ───────────────────────────────────

const typeBadgeVariant: Record<CharType, string> = {
  enum: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  numeric: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
  boolean: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
  text: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400",
}

// ── Form schema ──────────────────────────────────────────

const characteristicFormSchema = z.object({
  name: z.string().min(1, "Name is required").max(200),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(200)
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Must be a valid slug (lowercase, hyphens only)"),
  group_id: z.string().nullable().optional(),
  char_type: z.enum(["enum", "numeric", "boolean", "text"]),
  description: z.string().nullable().optional(),
  // Numeric-specific fields
  numeric_min: z.coerce.number().nullable().optional(),
  numeric_max: z.coerce.number().nullable().optional(),
  numeric_step: z.coerce.number().nullable().optional(),
  unit: z.string().nullable().optional(),
  // Toggles
  is_required: z.boolean().optional(),
  is_multi_select: z.boolean().optional(),
  default_value: z.string().nullable().optional(),
  display_order: z.coerce.number().optional(),
})

type CharacteristicFormValues = z.infer<typeof characteristicFormSchema>

// ── Main component ────────────────────────────────────────

export function CharacteristicsLibrary() {
  const [search, setSearch] = useState("")
  const [groupFilter, setGroupFilter] = useState<string>("all")
  const [typeFilter, setTypeFilter] = useState<string>("all")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingChar, setEditingChar] = useState<Characteristic | null>(null)
  const [groupsPanelOpen, setGroupsPanelOpen] = useState(false)

  // Build filters for the query
  const queryFilters = useMemo(
    () => ({
      group_id: groupFilter !== "all" ? groupFilter : undefined,
      char_type: typeFilter !== "all" ? typeFilter : undefined,
    }),
    [groupFilter, typeFilter],
  )

  const { data: charsData, isLoading, error, refetch } = useCharacteristics(queryFilters)
  const { data: groupsData } = useCharacteristicGroups()
  const deleteCharacteristic = useDeleteCharacteristic()

  const groups = useMemo(() => groupsData?.items ?? [], [groupsData])
  const groupMap = useMemo(
    () => new Map(groups.map((g) => [g.id, g.name])),
    [groups],
  )

  const characteristics = useMemo(() => {
    const items = charsData?.items ?? []
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q) ||
        (c.description && c.description.toLowerCase().includes(q)),
    )
  }, [charsData, search])

  const handleDelete = async (char: Characteristic) => {
    try {
      await deleteCharacteristic.mutateAsync(char.id)
    } catch {
      toast.error("Failed to delete characteristic")
    }
  }

  const handleEdit = (char: Characteristic) => {
    setEditingChar(char)
    setDialogOpen(true)
  }

  const handleCreate = () => {
    setEditingChar(null)
    setDialogOpen(true)
  }

  const handleDialogClose = () => {
    setDialogOpen(false)
    setEditingChar(null)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Characteristics Library"
        actions={
          <>
            <Button variant="outline" onClick={() => setGroupsPanelOpen(true)}>
              <Layers className="mr-2 h-4 w-4" />
              Manage Groups
            </Button>
            <Button onClick={handleCreate}>
              <Plus className="mr-2 h-4 w-4" />
              New Characteristic
            </Button>
          </>
        }
      />

      {/* Filter bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search characteristics..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={groupFilter} onValueChange={setGroupFilter}>
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Group" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All groups</SelectItem>
            {groups.map((g) => (
              <SelectItem key={g.id} value={g.id}>
                {g.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-full sm:w-[150px]">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="enum">Enum</SelectItem>
            <SelectItem value="numeric">Numeric</SelectItem>
            <SelectItem value="boolean">Boolean</SelectItem>
            <SelectItem value="text">Text</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Data table */}
      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <LoadingState variant="skeleton" rows={8} />
          ) : error ? (
            <ErrorState
              message={
                error instanceof Error
                  ? error.message
                  : "Failed to load characteristics."
              }
              onRetry={() => refetch()}
            />
          ) : characteristics.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              title="No characteristics yet"
              description="Create your first characteristic to define product options."
              action={
                <Button onClick={handleCreate}>
                  <Plus className="mr-2 h-4 w-4" />
                  Create your first characteristic
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead className="text-center">Required</TableHead>
                  <TableHead className="text-center">Values</TableHead>
                  <TableHead className="w-[50px]">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {characteristics.map((char) => (
                  <TableRow key={char.id}>
                    <TableCell className="font-medium">
                      <Link
                        to="/settings/characteristics/$charId"
                        params={{ charId: char.id }}
                        className="hover:underline"
                      >
                        {char.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono text-muted-foreground">
                        {char.slug}
                      </code>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          typeBadgeVariant[char.char_type] ?? typeBadgeVariant.text
                        }`}
                      >
                        {char.char_type}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {char.group_id ? groupMap.get(char.group_id) ?? "-" : "-"}
                    </TableCell>
                    <TableCell className="text-center">
                      {char.is_required ? (
                        <Check className="h-4 w-4 text-primary mx-auto" />
                      ) : (
                        <Minus className="h-4 w-4 text-muted-foreground/40 mx-auto" />
                      )}
                    </TableCell>
                    <TableCell className="text-center tabular-nums">
                      {char.char_type === "enum" ? (
                        <Badge variant="secondary" className="text-[10px]">
                          {char.values?.length ?? 0}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <CharacteristicActions
                        characteristic={char}
                        onEdit={handleEdit}
                        onDelete={handleDelete}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit dialog */}
      <CharacteristicFormDialog
        open={dialogOpen}
        onClose={handleDialogClose}
        characteristic={editingChar}
        groups={groups}
      />

      {/* Groups management panel */}
      <CharacteristicGroupsPanel
        open={groupsPanelOpen}
        onOpenChange={setGroupsPanelOpen}
      />
    </div>
  )
}

// ── Actions dropdown ────────────────────────────────────

function CharacteristicActions({
  characteristic,
  onEdit,
  onDelete,
}: {
  characteristic: Characteristic
  onEdit: (char: Characteristic) => void
  onDelete: (char: Characteristic) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          <MoreHorizontal className="h-4 w-4" />
          <span className="sr-only">Open menu</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link
            to="/settings/characteristics/$charId"
            params={{ charId: characteristic.id }}
          >
            <Eye className="mr-2 h-4 w-4" />
            View Details
          </Link>
        </DropdownMenuItem>
        {characteristic.char_type === "enum" && (
          <DropdownMenuItem asChild>
            <Link
              to="/settings/characteristics/$charId"
              params={{ charId: characteristic.id }}
            >
              <ListChecks className="mr-2 h-4 w-4" />
              Manage Values
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => onEdit(characteristic)}>
          <Pencil className="mr-2 h-4 w-4" />
          Edit
        </DropdownMenuItem>
        <ConfirmDialog
          title="Delete characteristic"
          description={`Are you sure you want to delete "${characteristic.name}"? This will remove it from all product assignments. This action cannot be undone.`}
          variant="destructive"
          confirmLabel="Delete"
          onConfirm={() => onDelete(characteristic)}
        >
          <DropdownMenuItem
            onSelect={(e) => e.preventDefault()}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </DropdownMenuItem>
        </ConfirmDialog>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// ── Create / Edit Dialog ────────────────────────────────

function CharacteristicFormDialog({
  open,
  onClose,
  characteristic,
  groups,
}: {
  open: boolean
  onClose: () => void
  characteristic: Characteristic | null
  groups: { id: string; name: string }[]
}) {
  const isEditing = characteristic !== null
  const createCharacteristic = useCreateCharacteristic()
  const updateCharacteristic = useUpdateCharacteristic()

  const form = useForm<CharacteristicFormValues>({
    resolver: zodResolver(characteristicFormSchema),
    defaultValues: characteristic
      ? {
          name: characteristic.name,
          slug: characteristic.slug,
          group_id: characteristic.group_id,
          char_type: characteristic.char_type,
          description: characteristic.description ?? "",
          numeric_min: characteristic.numeric_min,
          numeric_max: characteristic.numeric_max,
          numeric_step: characteristic.numeric_step,
          unit: characteristic.unit ?? "",
          is_required: characteristic.is_required,
          is_multi_select: characteristic.is_multi_select,
          default_value: characteristic.default_value ?? "",
          display_order: characteristic.display_order,
        }
      : {
          name: "",
          slug: "",
          group_id: null,
          char_type: "enum" as CharType,
          description: "",
          numeric_min: null,
          numeric_max: null,
          numeric_step: null,
          unit: "",
          is_required: false,
          is_multi_select: false,
          default_value: "",
          display_order: 0,
        },
  })

  // Reset form when dialog opens with new data
  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      form.reset()
      onClose()
    }
  }

  // When the dialog opens with a characteristic, reset the form with its values
  // This handles the case where we edit different characteristics sequentially
  useEffect(() => {
    if (open && characteristic) {
      form.reset({
        name: characteristic.name,
        slug: characteristic.slug,
        group_id: characteristic.group_id,
        char_type: characteristic.char_type,
        description: characteristic.description ?? "",
        numeric_min: characteristic.numeric_min,
        numeric_max: characteristic.numeric_max,
        numeric_step: characteristic.numeric_step,
        unit: characteristic.unit ?? "",
        is_required: characteristic.is_required,
        is_multi_select: characteristic.is_multi_select,
        default_value: characteristic.default_value ?? "",
        display_order: characteristic.display_order,
      })
    } else if (open && !characteristic) {
      form.reset({
        name: "",
        slug: "",
        group_id: null,
        char_type: "enum",
        description: "",
        numeric_min: null,
        numeric_max: null,
        numeric_step: null,
        unit: "",
        is_required: false,
        is_multi_select: false,
        default_value: "",
        display_order: 0,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, characteristic])

  const watchedType = form.watch("char_type")

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    form.setValue("name", name)
    if (!isEditing) {
      form.setValue("slug", toSlug(name), {
        shouldValidate: form.formState.isSubmitted,
      })
    }
  }

  const onSubmit = async (values: CharacteristicFormValues) => {
    try {
      if (isEditing && characteristic) {
        await updateCharacteristic.mutateAsync({
          id: characteristic.id,
          data: {
            name: values.name,
            group_id: values.group_id || null,
            description: values.description || null,
            numeric_min: values.char_type === "numeric" ? values.numeric_min ?? null : null,
            numeric_max: values.char_type === "numeric" ? values.numeric_max ?? null : null,
            numeric_step: values.char_type === "numeric" ? values.numeric_step ?? null : null,
            unit: values.char_type === "numeric" ? values.unit || null : null,
            is_required: values.is_required ?? false,
            is_multi_select: values.is_multi_select ?? false,
            default_value: values.default_value || null,
            display_order: values.display_order ?? 0,
          },
        })
      } else {
        await createCharacteristic.mutateAsync({
          name: values.name,
          slug: values.slug,
          group_id: values.group_id || null,
          char_type: values.char_type,
          description: values.description || null,
          numeric_min: values.char_type === "numeric" ? values.numeric_min ?? null : null,
          numeric_max: values.char_type === "numeric" ? values.numeric_max ?? null : null,
          numeric_step: values.char_type === "numeric" ? values.numeric_step ?? null : null,
          unit: values.char_type === "numeric" ? values.unit || null : null,
          is_required: values.is_required ?? false,
          is_multi_select: values.is_multi_select ?? false,
          default_value: values.default_value || null,
          display_order: values.display_order ?? 0,
        })
      }
      form.reset()
      onClose()
    } catch {
      toast.error(`Failed to ${isEditing ? "update" : "create"} characteristic`)
    }
  }

  const isPending = createCharacteristic.isPending || updateCharacteristic.isPending

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Characteristic" : "New Characteristic"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the characteristic details. Enum values are managed separately."
              : "Create a new characteristic. You can add enum values after creation."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="char-name">Name</Label>
            <Input
              id="char-name"
              placeholder="e.g. Motor Power"
              {...form.register("name", { onChange: handleNameChange })}
            />
            {form.formState.errors.name && (
              <p className="text-sm text-destructive">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>

          {/* Slug */}
          <div className="space-y-2">
            <Label htmlFor="char-slug">Slug</Label>
            <Input
              id="char-slug"
              placeholder="motor-power"
              disabled={isEditing}
              {...form.register("slug")}
            />
            {form.formState.errors.slug && (
              <p className="text-sm text-destructive">
                {form.formState.errors.slug.message}
              </p>
            )}
            {isEditing && (
              <p className="text-xs text-muted-foreground">
                Slug cannot be changed after creation.
              </p>
            )}
          </div>

          {/* Type */}
          <div className="space-y-2">
            <Label htmlFor="char-type">Type</Label>
            <Select
              value={form.watch("char_type")}
              onValueChange={(val) =>
                form.setValue("char_type", val as CharType, { shouldValidate: true })
              }
              disabled={isEditing}
            >
              <SelectTrigger id="char-type">
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="enum">Enum</SelectItem>
                <SelectItem value="numeric">Numeric</SelectItem>
                <SelectItem value="boolean">Boolean</SelectItem>
                <SelectItem value="text">Text</SelectItem>
              </SelectContent>
            </Select>
            {isEditing && (
              <p className="text-xs text-muted-foreground">
                Type cannot be changed after creation.
              </p>
            )}
          </div>

          {/* Group */}
          <div className="space-y-2">
            <Label htmlFor="char-group">Group</Label>
            <Select
              value={form.watch("group_id") ?? "none"}
              onValueChange={(val) =>
                form.setValue("group_id", val === "none" ? null : val)
              }
            >
              <SelectTrigger id="char-group">
                <SelectValue placeholder="Select a group (optional)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {groups.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="char-description">Description</Label>
            <Textarea
              id="char-description"
              placeholder="Brief description of this characteristic..."
              rows={2}
              {...form.register("description")}
            />
          </div>

          {/* Numeric-specific fields */}
          {watchedType === "numeric" && (
            <div className="space-y-4 rounded-md border p-4 bg-muted/30">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Numeric Settings
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="char-min">Min Value</Label>
                  <Input
                    id="char-min"
                    type="number"
                    step="any"
                    placeholder="0"
                    {...form.register("numeric_min")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="char-max">Max Value</Label>
                  <Input
                    id="char-max"
                    type="number"
                    step="any"
                    placeholder="100"
                    {...form.register("numeric_max")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="char-step">Step</Label>
                  <Input
                    id="char-step"
                    type="number"
                    step="any"
                    placeholder="1"
                    {...form.register("numeric_step")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="char-unit">Unit</Label>
                  <Input
                    id="char-unit"
                    placeholder="e.g. kW, mm, kg"
                    {...form.register("unit")}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Toggles */}
          <div className="space-y-3 rounded-md border p-4">
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="char-required" className="text-sm font-medium">
                  Required
                </Label>
                <p className="text-xs text-muted-foreground">
                  Users must provide a value during configuration
                </p>
              </div>
              <Switch
                id="char-required"
                checked={form.watch("is_required") ?? false}
                onCheckedChange={(checked) => form.setValue("is_required", checked)}
              />
            </div>

            {watchedType === "enum" && (
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="char-multi" className="text-sm font-medium">
                    Multi-select
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Allow selecting multiple values
                  </p>
                </div>
                <Switch
                  id="char-multi"
                  checked={form.watch("is_multi_select") ?? false}
                  onCheckedChange={(checked) => form.setValue("is_multi_select", checked)}
                />
              </div>
            )}
          </div>

          {/* Default value */}
          <div className="space-y-2">
            <Label htmlFor="char-default">Default Value</Label>
            <Input
              id="char-default"
              placeholder="Optional default value"
              {...form.register("default_value")}
            />
            <p className="text-xs text-muted-foreground">
              Pre-selected value when a new configuration session starts.
            </p>
          </div>

          {/* Display order */}
          <div className="space-y-2">
            <Label htmlFor="char-order">Display Order</Label>
            <Input
              id="char-order"
              type="number"
              placeholder="0"
              {...form.register("display_order")}
            />
          </div>

          {/* Enum notice */}
          {watchedType === "enum" && isEditing && (
            <div className="rounded-md border border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20 p-3">
              <p className="text-xs text-blue-800 dark:text-blue-400">
                Enum values for this characteristic are managed from the characteristic
                detail page. Save your changes here first, then navigate to manage values.
              </p>
            </div>
          )}

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
              {isPending
                ? "Saving..."
                : isEditing
                  ? "Update"
                  : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
