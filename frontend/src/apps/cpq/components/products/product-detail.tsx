import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { ArrowLeft, Play, GitBranch, Pencil } from "lucide-react"
import { useProduct, useUpdateProduct, useProductFamilies } from "@/apps/cpq/hooks/use-products"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Product, ProductStatus } from "@/apps/cpq/types/configurator"
import { ProductCharacteristics } from "./product-characteristics"
import { ProductConstraints } from "./product-constraints"
import { ProductBOM } from "./product-bom"
import { ProductPricing } from "./product-pricing"
import { ProductVersions } from "./product-versions"

// ── Status badge variant mapping ────────────────────────

const statusVariant = {
  draft: "secondary",
  active: "default",
  deprecated: "outline",
  archived: "destructive",
} as const

// ── Overview form schema ────────────────────────────────

const productOverviewSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable().optional(),
  sku_prefix: z.string().nullable().optional(),
  family_id: z.string().nullable().optional(),
  status: z.enum(["draft", "active", "deprecated", "archived"]),
  metadata: z.string().nullable().optional(),
})

type ProductOverviewFormValues = z.infer<typeof productOverviewSchema>

// ── ProductOverview sub-component ───────────────────────

function ProductOverview({ product }: { product: Product }) {
  const { t } = useTranslation()
  const updateProduct = useUpdateProduct()
  const { data: familiesData } = useProductFamilies()
  const families = familiesData?.items ?? []

  const form = useForm<ProductOverviewFormValues>({
    resolver: zodResolver(productOverviewSchema),
    defaultValues: {
      name: product.name,
      description: product.description ?? "",
      sku_prefix: product.sku_prefix ?? "",
      family_id: product.family_id ?? "",
      status: product.status,
      metadata: product.metadata ? JSON.stringify(product.metadata, null, 2) : "",
    },
  })

  function onSubmit(values: ProductOverviewFormValues) {
    let parsedMetadata: Record<string, unknown> | null = null
    if (values.metadata && values.metadata.trim()) {
      try {
        parsedMetadata = JSON.parse(values.metadata)
      } catch {
        form.setError("metadata", { message: "Invalid JSON" })
        return
      }
    }

    updateProduct.mutate({
      id: product.id,
      data: {
        name: values.name,
        description: values.description || null,
        sku_prefix: values.sku_prefix || null,
        family_id: values.family_id || null,
        status: values.status as ProductStatus,
        metadata: parsedMetadata,
      },
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("products.overview", "Product Overview")}</CardTitle>
        <CardDescription>
          {t("products.overviewDescription", "Edit the core product information.")}
        </CardDescription>
      </CardHeader>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)}>
          <CardContent className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("common.name", "Name")}</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormItem>
              <FormLabel>{t("common.slug", "Slug")}</FormLabel>
              <Input value={product.slug} disabled />
              <FormDescription>
                {t("products.slugReadOnly", "The slug is set at creation and cannot be changed.")}
              </FormDescription>
            </FormItem>

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
                      placeholder={t("products.descriptionPlaceholder", "Optional product description...")}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="sku_prefix"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("products.skuPrefix", "SKU Prefix")}</FormLabel>
                    <FormControl>
                      <Input {...field} value={field.value ?? ""} placeholder="e.g. PROD-" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="family_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("products.family", "Family")}</FormLabel>
                    <Select
                      value={field.value ?? ""}
                      onValueChange={(val) => field.onChange(val === "__none__" ? "" : val)}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={t("products.selectFamily", "Select family...")} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="__none__">
                          {t("common.none", "None")}
                        </SelectItem>
                        {families.map((f) => (
                          <SelectItem key={f.id} value={f.id}>
                            {f.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("common.status", "Status")}</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="draft">{t("products.statusDraft", "Draft")}</SelectItem>
                      <SelectItem value="active">{t("products.statusActive", "Active")}</SelectItem>
                      <SelectItem value="deprecated">{t("products.statusDeprecated", "Deprecated")}</SelectItem>
                      <SelectItem value="archived">{t("products.statusArchived", "Archived")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="metadata"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("common.metadata", "Metadata")}</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      value={field.value ?? ""}
                      rows={5}
                      className="font-mono text-xs"
                      placeholder='{ "key": "value" }'
                    />
                  </FormControl>
                  <FormDescription>
                    {t("products.metadataHelp", "Optional JSON metadata. Must be valid JSON if provided.")}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
          <CardFooter>
            <Button type="submit" disabled={updateProduct.isPending}>
              {updateProduct.isPending
                ? t("common.saving", "Saving...")
                : t("common.update", "Update")}
            </Button>
          </CardFooter>
        </form>
      </Form>
    </Card>
  )
}

// ── Loading skeleton ────────────────────────────────────

function ProductDetailSkeleton() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-48" />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-10 w-24" />
            <Skeleton className="h-10 w-32" />
            <Skeleton className="h-10 w-40" />
          </div>
        </div>
      </div>

      {/* Tabs skeleton */}
      <Skeleton className="h-10 w-full max-w-2xl" />

      {/* Content skeleton */}
      <div className="rounded-xl border p-6 space-y-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-64" />
        <div className="space-y-3 pt-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-20 w-full" />
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────

interface ProductDetailProps {
  productId: string
}

export function ProductDetail({ productId }: ProductDetailProps) {
  const { t } = useTranslation()
  const { data: product, isLoading } = useProduct(productId)
  const [activeTab, setActiveTab] = useState("overview")

  if (isLoading) return <ProductDetailSkeleton />
  if (!product) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <h3 className="text-lg font-semibold">{t("products.notFound", "Product not found")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("products.notFoundDescription", "The requested product does not exist or has been removed.")}
        </p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/products">
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t("products.backToList", "Back to Products")}
          </Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* ── Breadcrumb + Header ── */}
      <div className="space-y-3">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/products">{t("nav.products", "Products")}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{product.name}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
              {product.name}
            </h1>
            <Badge variant={statusVariant[product.status]}>
              {t(`products.status${product.status.charAt(0).toUpperCase() + product.status.slice(1)}`, product.status)}
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setActiveTab("overview")}
            >
              <Pencil className="mr-2 h-4 w-4" />
              {t("common.edit", "Edit")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setActiveTab("versions")}
            >
              <GitBranch className="mr-2 h-4 w-4" />
              {t("products.publishVersion", "Publish Version")}
            </Button>
            <Button size="sm" asChild>
              <Link to="/configurator/$productId" params={{ productId }}>
                <Play className="mr-2 h-4 w-4" />
                {t("products.launchConfigurator", "Launch Configurator")}
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {/* ── Tabbed content ── */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">
            {t("products.tabOverview", "Overview")}
          </TabsTrigger>
          <TabsTrigger value="characteristics">
            {t("products.tabCharacteristics", "Characteristics")}
          </TabsTrigger>
          <TabsTrigger value="constraints">
            {t("products.tabConstraints", "Constraints")}
          </TabsTrigger>
          <TabsTrigger value="bom">
            {t("products.tabBOM", "BOM")}
          </TabsTrigger>
          <TabsTrigger value="pricing">
            {t("products.tabPricing", "Pricing")}
          </TabsTrigger>
          <TabsTrigger value="versions">
            {t("products.tabVersions", "Versions")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <ProductOverview product={product} />
        </TabsContent>
        <TabsContent value="characteristics">
          <ProductCharacteristics productId={productId} />
        </TabsContent>
        <TabsContent value="constraints">
          <ProductConstraints productId={productId} />
        </TabsContent>
        <TabsContent value="bom">
          <ProductBOM productId={productId} />
        </TabsContent>
        <TabsContent value="pricing">
          <ProductPricing productId={productId} />
        </TabsContent>
        <TabsContent value="versions">
          <ProductVersions productId={productId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
