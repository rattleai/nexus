import { useState } from "react"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Plus, Pencil, Trash2, FolderTree } from "lucide-react"
import {
  useProductFamilies,
  useCreateProductFamily,
  useUpdateProductFamily,
  useDeleteProductFamily,
} from "@/apps/cpq/hooks/use-products"
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
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
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
import type { ProductFamily } from "@/apps/cpq/types/configurator"

// ── Form schema ─────────────────────────────────────────

const familyFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  slug: z.string().min(1, "Slug is required").regex(/^[a-z0-9-]+$/, "Slug must be lowercase alphanumeric with dashes"),
  description: z.string().nullable().optional(),
})

type FamilyFormValues = z.infer<typeof familyFormSchema>

// ── Family form dialog ──────────────────────────────────

function FamilyFormDialog({
  family,
  open,
  onOpenChange,
}: {
  family?: ProductFamily | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const createFamily = useCreateProductFamily()
  const updateFamily = useUpdateProductFamily()
  const isEditing = !!family

  const form = useForm<FamilyFormValues>({
    resolver: zodResolver(familyFormSchema),
    defaultValues: {
      name: family?.name ?? "",
      slug: family?.slug ?? "",
      description: family?.description ?? "",
    },
  })

  function onSubmit(values: FamilyFormValues) {
    if (isEditing && family) {
      updateFamily.mutate(
        {
          id: family.id,
          data: {
            name: values.name,
            description: values.description || null,
          },
        },
        {
          onSuccess: () => {
            onOpenChange(false)
            form.reset()
          },
        },
      )
    } else {
      createFamily.mutate(
        {
          name: values.name,
          slug: values.slug,
          description: values.description || null,
        },
        {
          onSuccess: () => {
            onOpenChange(false)
            form.reset()
          },
        },
      )
    }
  }

  const isPending = isEditing ? updateFamily.isPending : createFamily.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isEditing
              ? t("families.editFamily", "Edit Family")
              : t("families.createFamily", "Create Family")}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? t("families.editDescription", "Update the product family details.")
              : t("families.createDescription", "Create a new product family to group related products.")}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("common.name", "Name")}</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder={t("families.namePlaceholder", "e.g. Industrial Pumps")} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="slug"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("common.slug", "Slug")}</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder="e.g. industrial-pumps"
                      disabled={isEditing}
                    />
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
                  <FormLabel>{t("common.description", "Description")}</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      value={field.value ?? ""}
                      rows={3}
                      placeholder={t("families.descriptionPlaceholder", "Optional family description...")}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
                {t("common.cancel", "Cancel")}
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending
                  ? t("common.saving", "Saving...")
                  : isEditing
                    ? t("common.update", "Update")
                    : t("common.create", "Create")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

// ── Main component ──────────────────────────────────────

export function ProductFamilies() {
  const { t } = useTranslation()
  const { data: familiesData, isLoading } = useProductFamilies()
  const deleteFamily = useDeleteProductFamily()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingFamily, setEditingFamily] = useState<ProductFamily | null>(null)

  const families = familiesData?.items ?? []

  function handleEdit(family: ProductFamily) {
    setEditingFamily(family)
    setDialogOpen(true)
  }

  function handleCreate() {
    setEditingFamily(null)
    setDialogOpen(true)
  }

  function handleDialogChange(open: boolean) {
    setDialogOpen(open)
    if (!open) setEditingFamily(null)
  }

  if (isLoading) {
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
            <CardTitle>{t("families.title", "Product Families")}</CardTitle>
            <CardDescription>
              {t("families.description", "Organize products into families for easier management.")}
            </CardDescription>
          </div>
          <Button size="sm" onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            {t("families.create", "Create Family")}
          </Button>
        </CardHeader>

        <CardContent>
          {families.length === 0 ? (
            <EmptyState
              icon={FolderTree}
              title={t("families.noFamilies", "No product families")}
              description={t(
                "families.noFamiliesDescription",
                "Create a product family to organize your products.",
              )}
              action={
                <Button size="sm" onClick={handleCreate}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t("families.create", "Create Family")}
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("common.name", "Name")}</TableHead>
                  <TableHead>{t("common.slug", "Slug")}</TableHead>
                  <TableHead>{t("common.description", "Description")}</TableHead>
                  <TableHead>{t("common.created", "Created")}</TableHead>
                  <TableHead className="w-24" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {families.map((family) => (
                  <TableRow key={family.id}>
                    <TableCell className="font-medium">{family.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono text-xs">
                        {family.slug}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
                      {family.description ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(family.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(family)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => deleteFamily.mutate(family.id)}
                          disabled={deleteFamily.isPending}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <FamilyFormDialog
        family={editingFamily}
        open={dialogOpen}
        onOpenChange={handleDialogChange}
      />
    </>
  )
}
