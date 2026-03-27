import { useState, useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Package, ChevronRight, ChevronDown, Plus, Pencil, Trash2, MoreHorizontal } from "lucide-react"
import { useBOMs, useBOM, useCreateBOM, useUpdateBOM, useDeleteBOM, useDeleteBOMItem } from "@/apps/cpq/hooks/use-boms"
import { useCharacteristicAssignments } from "@/apps/cpq/hooks/use-characteristics"
import { ConditionSummary } from "@/apps/cpq/components/condition-builder"
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
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { BOMItemSheet } from "./bom/bom-item-sheet"
import type { BOMHeader, BOMItem, BOMItemType, Characteristic } from "@/apps/cpq/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductBOMProps {
  productId: string
}

// ── Item type badge mapping ─────────────────────────────

const itemTypeVariant: Record<
  BOMItemType,
  "default" | "secondary" | "outline" | "destructive"
> = {
  component: "default",
  sub_assembly: "secondary",
  phantom: "outline",
  reference: "destructive",
}

// ── Helpers ─────────────────────────────────────────────

function flattenItems(items: BOMItem[]): BOMItem[] {
  const seen = new Set<string>()
  const result: BOMItem[] = []
  function walk(list: BOMItem[]) {
    for (const item of list) {
      if (!seen.has(item.id)) {
        seen.add(item.id)
        result.push(item)
        if (item.children?.length) walk(item.children)
      }
    }
  }
  walk(items)
  return result
}

// ── BOM Header Form Schema ──────────────────────────────

const bomFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable().optional(),
  bom_type: z.enum(["manufacturing", "engineering", "service"]),
  is_primary: z.boolean(),
  effective_from: z.string().nullable().optional(),
  effective_to: z.string().nullable().optional(),
})

type BOMFormValues = z.infer<typeof bomFormSchema>

// ── BOM Header Form Dialog ──────────────────────────────

function BOMHeaderFormDialog({
  productId,
  bom,
  open,
  onOpenChange,
  onCreated,
}: {
  productId: string
  bom?: BOMHeader | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (id: string) => void
}) {
  const createBOM = useCreateBOM()
  const updateBOM = useUpdateBOM()
  const isEditing = !!bom

  const form = useForm<BOMFormValues>({
    resolver: zodResolver(bomFormSchema),
    defaultValues: {
      name: bom?.name ?? "",
      description: bom?.description ?? "",
      bom_type: (bom?.bom_type as BOMFormValues["bom_type"]) ?? "manufacturing",
      is_primary: bom?.is_primary ?? false,
      effective_from: bom?.effective_from ?? "",
      effective_to: bom?.effective_to ?? "",
    },
  })

  // Reset form values when bom or open state changes
  useEffect(() => {
    if (open) {
      form.reset({
        name: bom?.name ?? "",
        description: bom?.description ?? "",
        bom_type: (bom?.bom_type as BOMFormValues["bom_type"]) ?? "manufacturing",
        is_primary: bom?.is_primary ?? false,
        effective_from: bom?.effective_from ?? "",
        effective_to: bom?.effective_to ?? "",
      })
    }
  }, [open, bom, form])

  function onSubmit(values: BOMFormValues) {
    const payload = {
      name: values.name,
      description: values.description || null,
      bom_type: values.bom_type,
      is_primary: values.is_primary,
      effective_from: values.effective_from || null,
      effective_to: values.effective_to || null,
    }

    if (isEditing && bom) {
      updateBOM.mutate(
        { id: bom.id, data: payload },
        {
          onSuccess: () => {
            onOpenChange(false)
            form.reset()
          },
        },
      )
    } else {
      createBOM.mutate(
        { product_id: productId, ...payload },
        {
          onSuccess: (created) => {
            onOpenChange(false)
            form.reset()
            onCreated?.(created.id)
          },
        },
      )
    }
  }

  const isPending = isEditing ? updateBOM.isPending : createBOM.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit BOM" : "Create BOM"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the bill of materials header details."
              : "Create a new bill of materials for this product."}
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
                    <Input {...field} placeholder="e.g. Main Assembly BOM" />
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
              name="bom_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>BOM Type</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select type..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="manufacturing">Manufacturing</SelectItem>
                      <SelectItem value="engineering">Engineering</SelectItem>
                      <SelectItem value="service">Service</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="is_primary"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <FormLabel>Primary BOM</FormLabel>
                    <p className="text-sm text-muted-foreground">
                      Mark this as the default BOM for the product.
                    </p>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />

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
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
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

// ── Recursive BOM item row ──────────────────────────────

function BOMItemRow({
  item,
  depth,
  bomId,
  characteristics,
  allItems,
  onEdit,
  onAddChild,
}: {
  item: BOMItem
  depth: number
  bomId: string
  characteristics: Characteristic[]
  allItems: BOMItem[]
  onEdit: (item: BOMItem) => void
  onAddChild: (parentId: string) => void
}) {
  const [expanded, setExpanded] = useState(depth < 1)
  const hasChildren = item.children && item.children.length > 0
  const deleteItem = useDeleteBOMItem()
  const hasCondition = item.selection_condition != null

  return (
    <>
      <TableRow className={hasCondition ? "border-l-2 border-l-blue-500" : ""}>
        <TableCell style={{ paddingLeft: `${depth * 24 + 16}px` }}>
          <div className="flex items-center gap-1">
            {hasChildren ? (
              <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="p-0.5 rounded hover:bg-muted"
              >
                {expanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </button>
            ) : (
              <span className="w-5" />
            )}
            <span className="font-medium text-sm">{item.part_number}</span>
          </div>
        </TableCell>
        <TableCell className="text-sm">{item.part_name}</TableCell>
        <TableCell>
          <Badge variant={itemTypeVariant[item.item_type]}>{item.item_type}</Badge>
        </TableCell>
        <TableCell className="text-sm text-right">
          {item.quantity} {item.unit_of_measure}
        </TableCell>
        <TableCell className="text-sm text-right text-muted-foreground">
          {item.unit_cost != null ? `$${Number(item.unit_cost).toFixed(2)}` : "\u2014"}
        </TableCell>
        <TableCell>
          {item.is_optional && (
            <Badge variant="outline">Optional</Badge>
          )}
        </TableCell>
        <TableCell className="max-w-[200px]">
          {hasCondition ? (
            <ConditionSummary
              condition={item.selection_condition as import("@/components/condition-builder").ConditionNode}
              characteristics={characteristics}
              className="text-xs truncate block"
            />
          ) : (
            <span className="text-xs text-muted-foreground italic">Always</span>
          )}
        </TableCell>
        <TableCell>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Actions</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onEdit(item)}>
                <Pencil className="h-4 w-4 mr-2" />
                Edit
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onAddChild(item.id)}>
                <Plus className="h-4 w-4 mr-2" />
                Add Child
              </DropdownMenuItem>
              <ConfirmDialog
                title="Delete Item"
                description={`Are you sure you want to delete "${item.part_number} - ${item.part_name}"? Any child items will also be deleted. This action cannot be undone.`}
                confirmLabel="Delete"
                variant="destructive"
                onConfirm={() =>
                  deleteItem.mutate({ bomId, itemId: item.id })
                }
              >
                <button
                  type="button"
                  className="relative flex w-full cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </button>
              </ConfirmDialog>
            </DropdownMenuContent>
          </DropdownMenu>
        </TableCell>
      </TableRow>
      {expanded &&
        hasChildren &&
        item.children.map((child) => (
          <BOMItemRow
            key={child.id}
            item={child}
            depth={depth + 1}
            bomId={bomId}
            characteristics={characteristics}
            allItems={allItems}
            onEdit={onEdit}
            onAddChild={onAddChild}
          />
        ))}
    </>
  )
}

// ── Component ───────────────────────────────────────────

export function ProductBOM({ productId }: ProductBOMProps) {
  const { data: bomsData, isLoading: loadingBOMs } = useBOMs(productId)
  const deleteBOM = useDeleteBOM()

  // BOM header state
  const [selectedBOMId, setSelectedBOMId] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingBOM, setEditingBOM] = useState<BOMHeader | null>(null)

  // BOM item state
  const [itemSheetOpen, setItemSheetOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<BOMItem | null>(null)
  const [parentItemId, setParentItemId] = useState<string | null>(null)

  const boms = bomsData?.items ?? []

  // Auto-select first BOM if available, or clear selection if list is empty
  const activeBOMId = selectedBOMId && boms.some((b) => b.id === selectedBOMId)
    ? selectedBOMId
    : boms.length > 0
      ? boms[0].id
      : null

  const { data: bomDetail, isLoading: loadingDetail } = useBOM(activeBOMId)

  // Fetch characteristics assigned to this product
  const { data: charData } = useCharacteristicAssignments(productId)
  const characteristics: Characteristic[] = charData?.items ?? []

  // Flatten all items for the parent selector
  const allItems = bomDetail ? flattenItems(bomDetail.items) : []

  // Find the active BOM header object (for edit)
  const activeBOM = boms.find((b) => b.id === activeBOMId) ?? null

  function handleCreate() {
    setEditingBOM(null)
    setDialogOpen(true)
  }

  function handleEdit() {
    if (activeBOM) {
      setEditingBOM(activeBOM)
      setDialogOpen(true)
    }
  }

  function handleDelete() {
    if (!activeBOMId) return
    deleteBOM.mutate(activeBOMId, {
      onSuccess: () => {
        // After deletion, clear selection so auto-select picks the first remaining
        setSelectedBOMId(null)
      },
    })
  }

  function handleCreated(id: string) {
    setSelectedBOMId(id)
  }

  // Item sheet handlers
  function handleAddItem() {
    setEditingItem(null)
    setParentItemId(null)
    setItemSheetOpen(true)
  }

  function handleEditItem(item: BOMItem) {
    setEditingItem(item)
    setParentItemId(null)
    setItemSheetOpen(true)
  }

  function handleAddChild(parentId: string) {
    setEditingItem(null)
    setParentItemId(parentId)
    setItemSheetOpen(true)
  }

  if (loadingBOMs) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
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
          <div className="space-y-1.5">
            <CardTitle>Bill of Materials</CardTitle>
            <CardDescription>
              Manage the product's bill of materials.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {boms.length > 0 && (
              <>
                <Select
                  value={activeBOMId ?? ""}
                  onValueChange={(val) => setSelectedBOMId(val)}
                >
                  <SelectTrigger className="w-[200px]">
                    <SelectValue placeholder="Select BOM..." />
                  </SelectTrigger>
                  <SelectContent>
                    {boms.map((b) => (
                      <SelectItem key={b.id} value={b.id}>
                        {b.name}
                        {b.is_primary && " (Primary)"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleEdit}
                  title="Edit BOM"
                >
                  <Pencil className="h-4 w-4" />
                </Button>

                <ConfirmDialog
                  title="Delete BOM"
                  description="Are you sure you want to delete this BOM? All items within it will also be permanently deleted. This action cannot be undone."
                  confirmLabel="Delete"
                  variant="destructive"
                  onConfirm={handleDelete}
                >
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Delete BOM"
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </ConfirmDialog>
              </>
            )}

            <Button size="sm" onClick={handleCreate}>
              <Plus className="h-4 w-4 mr-1" />
              Create BOM
            </Button>
          </div>
        </CardHeader>

        <CardContent>
          {boms.length === 0 ? (
            <EmptyState
              icon={Package}
              title="No bill of materials"
              description="Create a BOM to define the component structure of this product."
              action={
                <Button size="sm" onClick={handleCreate}>
                  <Plus className="h-4 w-4 mr-1" />
                  Create BOM
                </Button>
              }
            />
          ) : loadingDetail ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : bomDetail ? (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span>
                    Type: <Badge variant="outline">{bomDetail.bom_type}</Badge>
                  </span>
                  {bomDetail.is_primary && (
                    <Badge variant="default">Primary</Badge>
                  )}
                  {bomDetail.effective_from && (
                    <span>From: {bomDetail.effective_from}</span>
                  )}
                  {bomDetail.effective_to && (
                    <span>To: {bomDetail.effective_to}</span>
                  )}
                </div>
                <Button size="sm" variant="outline" onClick={handleAddItem}>
                  <Plus className="h-4 w-4 mr-1" />
                  Add Item
                </Button>
              </div>

              {bomDetail.items.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Part Number</TableHead>
                      <TableHead>Part Name</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Unit Cost</TableHead>
                      <TableHead>Flags</TableHead>
                      <TableHead>Condition</TableHead>
                      <TableHead className="w-[50px]">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {bomDetail.items.map((item) => (
                      <BOMItemRow
                        key={item.id}
                        item={item}
                        depth={0}
                        bomId={activeBOMId!}
                        characteristics={characteristics}
                        allItems={allItems}
                        onEdit={handleEditItem}
                        onAddChild={handleAddChild}
                      />
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  icon={Package}
                  title="No items in this BOM"
                  description="Add components to build the product structure."
                  action={
                    <Button size="sm" onClick={handleAddItem}>
                      <Plus className="h-4 w-4 mr-1" />
                      Add Item
                    </Button>
                  }
                />
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <BOMHeaderFormDialog
        productId={productId}
        bom={editingBOM}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCreated={handleCreated}
      />

      {activeBOMId && (
        <BOMItemSheet
          open={itemSheetOpen}
          onOpenChange={setItemSheetOpen}
          bomId={activeBOMId}
          productId={productId}
          editItem={editingItem}
          parentItemId={parentItemId}
          allItems={allItems}
          characteristics={characteristics}
        />
      )}
    </>
  )
}
