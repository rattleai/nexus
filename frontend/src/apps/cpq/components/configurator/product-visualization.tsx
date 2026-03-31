import { Package } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useProduct } from "@/apps/cpq/hooks/use-products"

interface ProductVisualizationProps {
  productId: string
  selections: Record<string, string>
}

export function ProductVisualization({
  productId,
  selections,
}: ProductVisualizationProps) {
  const { data: product } = useProduct(productId)

  const selectionEntries = Object.entries(selections)
  const hasSelections = selectionEntries.length > 0

  return (
    <div className="relative flex min-h-[400px] flex-col items-center justify-center overflow-hidden rounded-xl p-8">
      {/* Radial gradient background */}
      <div
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse at center, hsl(var(--muted)) 0%, hsl(var(--background)) 70%)",
        }}
      />

      {/* Selection badges ring (top arc) */}
      {hasSelections && (
        <div className="mb-8 flex max-w-md flex-wrap items-center justify-center gap-2">
          {selectionEntries.slice(0, Math.ceil(selectionEntries.length / 2)).map(
            ([charSlug, value]) => (
              <Badge
                key={charSlug}
                variant="secondary"
                className="transition-all duration-300 ease-in-out"
              >
                <span className="text-muted-foreground">{charSlug}:</span>
                <span className="ml-1 font-medium">{value}</span>
              </Badge>
            ),
          )}
        </div>
      )}

      {/* Center: Product icon and name */}
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-24 w-24 items-center justify-center rounded-full border-2 border-dashed border-muted-foreground/20 bg-muted/50">
          <Package className="h-12 w-12 text-muted-foreground/60" strokeWidth={1.5} />
        </div>
        <div className="text-center">
          <h2 className="text-2xl font-semibold tracking-tight">
            {product?.name ?? "Loading..."}
          </h2>
          {product?.description && (
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              {product.description}
            </p>
          )}
        </div>
      </div>

      {/* Selection badges ring (bottom arc) */}
      {hasSelections && selectionEntries.length > 1 && (
        <div className="mt-8 flex max-w-md flex-wrap items-center justify-center gap-2">
          {selectionEntries.slice(Math.ceil(selectionEntries.length / 2)).map(
            ([charSlug, value]) => (
              <Badge
                key={charSlug}
                variant="secondary"
                className="transition-all duration-300 ease-in-out"
              >
                <span className="text-muted-foreground">{charSlug}:</span>
                <span className="ml-1 font-medium">{value}</span>
              </Badge>
            ),
          )}
        </div>
      )}

      {/* Empty state when no selections */}
      {!hasSelections && (
        <p className="mt-6 text-sm text-muted-foreground">
          Select options to see your configuration
        </p>
      )}

      {/* Future placeholder note */}
      <p className="mt-auto pt-8 text-xs text-muted-foreground/50">
        Image gallery coming soon
      </p>
    </div>
  )
}
