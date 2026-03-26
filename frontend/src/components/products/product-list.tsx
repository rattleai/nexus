import { useState, useMemo } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import {
  Plus,
  Search,
  MoreHorizontal,
  Pencil,
  Settings2,
  Trash2,
  Package,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent } from "@/components/ui/card"
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import {
  useProducts,
  useCreateProduct,
  useDeleteProduct,
  useProductFamilies,
} from "@/hooks/use-products"
import type { Product } from "@/types/configurator"

// ── Status badge variant mapping ────────────────────────

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "secondary",
  active: "default",
  deprecated: "outline",
  archived: "destructive",
}

// ── Slug helper ─────────────────────────────────────────

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
}

// ── Create Product form schema ──────────────────────────

const createProductSchema = z.object({
  name: z.string().min(1, "Name is required").max(200),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(200)
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Must be a valid slug (lowercase, hyphens only)"),
  family_id: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  sku_prefix: z.string().max(50).nullable().optional(),
})

type CreateProductValues = z.infer<typeof createProductSchema>

// ── Date formatter ──────────────────────────────────────

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

// ── Main component ──────────────────────────────────────

export function ProductList() {
  const { t } = useTranslation()

  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [familyFilter, setFamilyFilter] = useState<string>("all")
  const [dialogOpen, setDialogOpen] = useState(false)

  const filters = useMemo(
    () => ({
      status: statusFilter !== "all" ? statusFilter : undefined,
      family_id: familyFilter !== "all" ? familyFilter : undefined,
    }),
    [statusFilter, familyFilter],
  )

  const { data, isLoading, error, refetch } = useProducts(filters)
  const { data: familiesData } = useProductFamilies()
  const deleteProduct = useDeleteProduct()

  const families = familiesData?.items ?? []
  const familyMap = useMemo(
    () => new Map(families.map((f) => [f.id, f.name])),
    [families],
  )

  const products = useMemo(() => {
    const items = data?.items ?? []
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q) ||
        (p.sku_prefix && p.sku_prefix.toLowerCase().includes(q)),
    )
  }, [data, search])

  const handleDelete = async (product: Product) => {
    try {
      await deleteProduct.mutateAsync(product.id)
    } catch {
      toast.error("Failed to delete product")
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.products", "Products")}
        actions={
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                {t("buttons.new_product", "New Product")}
              </Button>
            </DialogTrigger>
            <CreateProductDialog
              families={families}
              onCreated={() => setDialogOpen(false)}
            />
          </Dialog>
        }
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("labels.search", "Search...")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-[150px]">
            <SelectValue placeholder={t("labels.status", "Status")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="deprecated">Deprecated</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>
        <Select value={familyFilter} onValueChange={setFamilyFilter}>
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Family" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All families</SelectItem>
            {families.map((f) => (
              <SelectItem key={f.id} value={f.id}>
                {f.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Content */}
      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <LoadingState variant="skeleton" rows={5} />
          ) : error ? (
            <ErrorState
              message={error instanceof Error ? error.message : "Failed to load products."}
              onRetry={() => refetch()}
            />
          ) : products.length === 0 ? (
            <EmptyState
              icon={Package}
              title="No products yet"
              description="Create your first product to start building configurations."
              action={
                <Button onClick={() => setDialogOpen(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Create your first product
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>SKU Prefix</TableHead>
                  <TableHead>Family</TableHead>
                  <TableHead>{t("labels.status", "Status")}</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-[50px]">
                    <span className="sr-only">{t("labels.actions", "Actions")}</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {products.map((product) => (
                  <TableRow key={product.id}>
                    <TableCell className="font-medium">
                      <Link
                        to="/products/$productId"
                        params={{ productId: product.id }}
                        className="hover:underline"
                      >
                        {product.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {product.sku_prefix ?? "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {product.family_id ? familyMap.get(product.family_id) ?? "-" : "-"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant[product.status] ?? "secondary"}>
                        {product.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(product.updated_at)}
                    </TableCell>
                    <TableCell>
                      <ProductActions product={product} onDelete={handleDelete} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Actions dropdown ────────────────────────────────────

function ProductActions({
  product,
  onDelete,
}: {
  product: Product
  onDelete: (product: Product) => void
}) {
  const { t } = useTranslation()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          <MoreHorizontal className="h-4 w-4" />
          <span className="sr-only">{t("aria.open_menu", "Open menu")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to="/products/$productId" params={{ productId: product.id }}>
            <Pencil className="mr-2 h-4 w-4" />
            Edit
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/products/$productId" params={{ productId: product.id }} search={{ tab: "configure" }}>
            <Settings2 className="mr-2 h-4 w-4" />
            Configure
          </Link>
        </DropdownMenuItem>
        <ConfirmDialog
          title="Delete product"
          description={`Are you sure you want to delete "${product.name}"? This action cannot be undone.`}
          variant="destructive"
          confirmLabel={t("buttons.delete", "Delete")}
          onConfirm={() => onDelete(product)}
        >
          <DropdownMenuItem
            onSelect={(e) => e.preventDefault()}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {t("buttons.delete", "Delete")}
          </DropdownMenuItem>
        </ConfirmDialog>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// ── Create Product Dialog ───────────────────────────────

function CreateProductDialog({
  families,
  onCreated,
}: {
  families: { id: string; name: string }[]
  onCreated: () => void
}) {
  const { t } = useTranslation()
  const createProduct = useCreateProduct()

  const form = useForm<CreateProductValues>({
    resolver: zodResolver(createProductSchema),
    defaultValues: {
      name: "",
      slug: "",
      family_id: null,
      description: "",
      sku_prefix: "",
    },
  })

  const onSubmit = async (values: CreateProductValues) => {
    try {
      await createProduct.mutateAsync({
        name: values.name,
        slug: values.slug,
        family_id: values.family_id || null,
        description: values.description || null,
        sku_prefix: values.sku_prefix || null,
      })
      form.reset()
      onCreated()
    } catch {
      toast.error("Failed to create product")
    }
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    form.setValue("name", name)
    form.setValue("slug", toSlug(name), { shouldValidate: form.formState.isSubmitted })
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>New Product</DialogTitle>
        <DialogDescription>
          Create a new configurable product. You can add characteristics and rules after creation.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            placeholder="e.g. Industrial Pump X200"
            {...form.register("name", {
              onChange: handleNameChange,
            })}
          />
          {form.formState.errors.name && (
            <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="slug">Slug</Label>
          <Input
            id="slug"
            placeholder="industrial-pump-x200"
            {...form.register("slug")}
          />
          {form.formState.errors.slug && (
            <p className="text-sm text-destructive">{form.formState.errors.slug.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="family_id">Family</Label>
          <Select
            value={form.watch("family_id") ?? "none"}
            onValueChange={(val) =>
              form.setValue("family_id", val === "none" ? null : val)
            }
          >
            <SelectTrigger id="family_id">
              <SelectValue placeholder="Select a family (optional)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">None</SelectItem>
              {families.map((f) => (
                <SelectItem key={f.id} value={f.id}>
                  {f.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="sku_prefix">SKU Prefix</Label>
          <Input
            id="sku_prefix"
            placeholder="e.g. PUMP-X200"
            {...form.register("sku_prefix")}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            placeholder="Brief product description..."
            rows={3}
            {...form.register("description")}
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => { form.reset(); onCreated() }}>
            {t("buttons.cancel", "Cancel")}
          </Button>
          <Button type="submit" disabled={createProduct.isPending}>
            {createProduct.isPending ? t("buttons.saving", "Saving...") : t("buttons.create", "Create")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
