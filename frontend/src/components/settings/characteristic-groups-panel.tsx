import { useState, useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Plus, Pencil, Trash2, Layers } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { EmptyState } from "@/components/empty-state"
import { LoadingState } from "@/components/loading-state"
import {
  useCharacteristicGroups,
  useCreateCharacteristicGroup,
  useUpdateCharacteristicGroup,
  useDeleteCharacteristicGroup,
} from "@/hooks/use-characteristics"
import type { CharacteristicGroup } from "@/types/configurator"

// ── Slug helper ──────────────────────────────────────────

function toSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
}

// ── Form schema ──────────────────────────────────────────

const groupFormSchema = z.object({
  name: z.string().min(1, "Name is required").max(200),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(200)
    .regex(/^[a-z0-9]+(?:_[a-z0-9]+)*$/, "Must be a valid slug (lowercase, underscores only)"),
  description: z.string().nullable().optional(),
  display_order: z.coerce.number().optional().default(0),
})

type GroupFormValues = z.infer<typeof groupFormSchema>

// ── Main Panel Component ─────────────────────────────────

interface CharacteristicGroupsPanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CharacteristicGroupsPanel({
  open,
  onOpenChange,
}: CharacteristicGroupsPanelProps) {
  const { data: groupsData, isLoading } = useCharacteristicGroups()
  const deleteGroup = useDeleteCharacteristicGroup()

  const [formDialogOpen, setFormDialogOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<CharacteristicGroup | null>(null)

  const groups = groupsData?.items ?? []

  const handleCreate = () => {
    setEditingGroup(null)
    setFormDialogOpen(true)
  }

  const handleEdit = (group: CharacteristicGroup) => {
    setEditingGroup(group)
    setFormDialogOpen(true)
  }

  const handleDelete = async (group: CharacteristicGroup) => {
    try {
      await deleteGroup.mutateAsync(group.id)
    } catch {
      toast.error("Failed to delete group")
    }
  }

  const handleFormClose = () => {
    setFormDialogOpen(false)
    setEditingGroup(null)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-lg w-full flex flex-col">
        <SheetHeader>
          <SheetTitle>Characteristic Groups</SheetTitle>
          <SheetDescription>
            Organize characteristics into logical groups
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4">
          <Button onClick={handleCreate} size="sm">
            <Plus className="mr-2 h-4 w-4" />
            New Group
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto mt-4">
          {isLoading ? (
            <LoadingState variant="skeleton" rows={4} />
          ) : groups.length === 0 ? (
            <EmptyState
              icon={Layers}
              title="No groups yet"
              description="Create your first group to organize characteristics."
              action={
                <Button onClick={handleCreate} size="sm">
                  <Plus className="mr-2 h-4 w-4" />
                  Create your first group
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead className="text-center">Order</TableHead>
                  <TableHead className="w-[80px]">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((group) => (
                  <TableRow key={group.id}>
                    <TableCell>
                      <div>
                        <span className="font-medium">{group.name}</span>
                        {group.description && (
                          <p className="text-xs text-muted-foreground truncate max-w-[200px]">
                            {group.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono text-muted-foreground">
                        {group.slug}
                      </code>
                    </TableCell>
                    <TableCell className="text-center tabular-nums">
                      {group.display_order}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => handleEdit(group)}
                        >
                          <Pencil className="h-4 w-4" />
                          <span className="sr-only">Edit</span>
                        </Button>
                        <ConfirmDialog
                          title="Delete group"
                          description={`Are you sure you want to delete "${group.name}"? Characteristics in this group will become ungrouped. This action cannot be undone.`}
                          variant="destructive"
                          confirmLabel="Delete"
                          onConfirm={() => handleDelete(group)}
                        >
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-4 w-4" />
                            <span className="sr-only">Delete</span>
                          </Button>
                        </ConfirmDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        {/* Create/Edit dialog */}
        <GroupFormDialog
          open={formDialogOpen}
          onClose={handleFormClose}
          group={editingGroup}
        />
      </SheetContent>
    </Sheet>
  )
}

// ── Group Form Dialog ────────────────────────────────────

function GroupFormDialog({
  open,
  onClose,
  group,
}: {
  open: boolean
  onClose: () => void
  group: CharacteristicGroup | null
}) {
  const isEditing = group !== null
  const createGroup = useCreateCharacteristicGroup()
  const updateGroup = useUpdateCharacteristicGroup()

  const form = useForm<GroupFormValues>({
    resolver: zodResolver(groupFormSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: "",
      display_order: 0,
    },
  })

  // Reset form when dialog opens with new data
  useEffect(() => {
    if (open && group) {
      form.reset({
        name: group.name,
        slug: group.slug,
        description: group.description ?? "",
        display_order: group.display_order,
      })
    } else if (open && !group) {
      form.reset({
        name: "",
        slug: "",
        description: "",
        display_order: 0,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, group])

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      form.reset()
      onClose()
    }
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    form.setValue("name", name)
    if (!isEditing) {
      form.setValue("slug", toSlug(name), {
        shouldValidate: form.formState.isSubmitted,
      })
    }
  }

  const onSubmit = async (values: GroupFormValues) => {
    try {
      if (isEditing && group) {
        await updateGroup.mutateAsync({
          id: group.id,
          data: {
            name: values.name,
            description: values.description || null,
            display_order: values.display_order ?? 0,
          },
        })
      } else {
        await createGroup.mutateAsync({
          name: values.name,
          slug: values.slug,
          description: values.description || null,
          display_order: values.display_order ?? 0,
        })
      }
      form.reset()
      onClose()
    } catch {
      toast.error(`Failed to ${isEditing ? "update" : "create"} group`)
    }
  }

  const isPending = createGroup.isPending || updateGroup.isPending

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Group" : "New Group"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the group details."
              : "Create a new characteristic group."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="group-name">Name</Label>
            <Input
              id="group-name"
              placeholder="e.g. Engine Options"
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
            <Label htmlFor="group-slug">Slug</Label>
            <Input
              id="group-slug"
              placeholder="engine_options"
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

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="group-description">Description</Label>
            <Textarea
              id="group-description"
              placeholder="Brief description of this group..."
              rows={2}
              {...form.register("description")}
            />
          </div>

          {/* Display Order */}
          <div className="space-y-2">
            <Label htmlFor="group-order">Display Order</Label>
            <Input
              id="group-order"
              type="number"
              placeholder="0"
              {...form.register("display_order")}
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
