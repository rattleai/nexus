import { useEffect, useState, useCallback, useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { ArrowLeft, Share2, Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useProduct } from "@/hooks/use-products"
import {
  useCharacteristics,
  useCharacteristicGroups,
} from "@/hooks/use-characteristics"
import {
  useCreateSession,
  useMakeSelection,
  useCompleteSession,
} from "@/hooks/use-configurator"
import { useConfiguratorStore } from "@/stores/configurator-store"
import { StepNavigation } from "./step-navigation"
import { OptionSelector } from "./option-selector"
import { ProductVisualization } from "./product-visualization"
import { PriceSummaryBar } from "./price-summary-bar"
import { ConstraintFeedback } from "./constraint-feedback"
import { useIsMobile } from "@/hooks/use-mobile"
import { toast } from "sonner"
import type {
  Characteristic,
  SelectionResult,
} from "@/types/configurator"

interface ConfiguratorPageProps {
  productId: string
}

interface Step {
  slug: string
  name: string
  characteristicCount: number
}

export function ConfiguratorPage({ productId }: ConfiguratorPageProps) {
  const isMobile = useIsMobile()

  // ── Data queries ──────────────────────────────────────────
  const { data: product, isLoading: productLoading } = useProduct(productId)
  const { data: characteristicsData, isLoading: charsLoading } =
    useCharacteristics()
  const { data: groupsData, isLoading: groupsLoading } =
    useCharacteristicGroups()

  // ── Mutations ─────────────────────────────────────────────
  const createSession = useCreateSession()
  const makeSelection = useMakeSelection()
  const completeSession = useCompleteSession()
  // simulatePricing is used by PriceSummaryBar directly

  // ── Store ─────────────────────────────────────────────────
  const store = useConfiguratorStore()

  // ── Local state ───────────────────────────────────────────
  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  const [sessionError, setSessionError] = useState<string | null>(null)

  // ── Derived data ──────────────────────────────────────────
  const characteristics = useMemo(
    () => characteristicsData?.items ?? [],
    [characteristicsData],
  )

  const groups = useMemo(
    () =>
      [...(groupsData?.items ?? [])].sort(
        (a, b) => a.display_order - b.display_order,
      ),
    [groupsData],
  )

  // Build a map: group_id -> characteristics (sorted by display_order)
  const charsByGroup = useMemo(() => {
    const map = new Map<string | null, Characteristic[]>()
    for (const char of characteristics) {
      const key = char.group_id
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(char)
    }
    // Sort each group's characteristics
    for (const [, chars] of map) {
      chars.sort((a, b) => a.display_order - b.display_order)
    }
    return map
  }, [characteristics])

  // Build steps from groups + ungrouped characteristics
  const steps: Step[] = useMemo(() => {
    const result: Step[] = []

    for (const group of groups) {
      const chars = charsByGroup.get(group.id) ?? []
      if (chars.length > 0) {
        result.push({
          slug: group.slug,
          name: group.name,
          characteristicCount: chars.length,
        })
      }
    }

    // Ungrouped characteristics become a "General" step
    const ungrouped = charsByGroup.get(null) ?? []
    if (ungrouped.length > 0) {
      result.push({
        slug: "_general",
        name: "General",
        characteristicCount: ungrouped.length,
      })
    }

    return result
  }, [groups, charsByGroup])

  // Characteristics for the current step
  const currentCharacteristics: Characteristic[] = useMemo(() => {
    if (steps.length === 0) return []
    const step = steps[currentStepIndex]
    if (!step) return []

    if (step.slug === "_general") {
      return charsByGroup.get(null) ?? []
    }

    const group = groups.find((g) => g.slug === step.slug)
    if (!group) return []
    return charsByGroup.get(group.id) ?? []
  }, [steps, currentStepIndex, groups, charsByGroup])

  // Track completed steps (a step is complete when all its characteristics have a selection)
  const completedSteps: Set<string> = useMemo(() => {
    const completed = new Set<string>()
    for (const step of steps) {
      let chars: Characteristic[]
      if (step.slug === "_general") {
        chars = charsByGroup.get(null) ?? []
      } else {
        const group = groups.find((g) => g.slug === step.slug)
        chars = group ? (charsByGroup.get(group.id) ?? []) : []
      }
      if (chars.length === 0) continue

      const allSelected = chars.every(
        (c) =>
          store.selections[c.slug] !== undefined ||
          store.autoSetValues[c.slug] !== undefined,
      )
      if (allSelected) completed.add(step.slug)
    }
    return completed
  }, [steps, groups, charsByGroup, store.selections, store.autoSetValues])

  // ── Create session on mount ───────────────────────────────
  useEffect(() => {
    if (!productId || store.sessionId) return

    createSession.mutate(
      { product_id: productId },
      {
        onSuccess: (session) => {
          store.setSession(session.id, productId, product?.name ?? "")

          // Populate initial selections from session
          const initialSelections: Record<string, string> = {}
          for (const sel of session.selections) {
            // We need to find the characteristic slug from the id
            const char = characteristics.find(
              (c) => c.id === sel.characteristic_id,
            )
            if (char) {
              initialSelections[char.slug] = sel.value
              if (sel.is_auto_set) {
                store.setAutoSetValues({
                  ...store.autoSetValues,
                  [char.slug]: sel.value,
                })
              }
            }
          }

          // Update domains if available
          if (session.available_domains) {
            store.updateDomains(session.available_domains, {})
          }
        },
        onError: () => {
          setSessionError("Failed to create configuration session")
          toast.error("Failed to create configuration session")
        },
      },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId])

  // Update product name in store once loaded
  useEffect(() => {
    if (product?.name && store.sessionId && !store.productName) {
      store.setSession(store.sessionId, productId, product.name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product?.name])

  // Set step slugs in store when steps change
  useEffect(() => {
    if (steps.length > 0) {
      store.setStepSlugs(steps.map((s) => s.slug))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps])

  // Clean up store on unmount
  useEffect(() => {
    return () => {
      store.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Selection handler ─────────────────────────────────────
  const handleSelect = useCallback(
    (characteristicId: string, characteristicSlug: string, value: string) => {
      if (!store.sessionId) return

      // Optimistic update
      store.setSelection(characteristicSlug, value)
      store.setLoading(true)

      makeSelection.mutate(
        {
          sessionId: store.sessionId,
          data: { characteristic_id: characteristicId, value },
        },
        {
          onSuccess: (result: SelectionResult) => {
            // Update selections from session
            const newSelections: Record<string, string> = {}
            for (const sel of result.session.selections) {
              const c = characteristics.find(
                (ch) => ch.id === sel.characteristic_id,
              )
              if (c) {
                newSelections[c.slug] = sel.value
              }
            }
            // Apply all selections from the server
            for (const [slug, val] of Object.entries(newSelections)) {
              store.setSelection(slug, val)
            }

            // Update auto-set values
            store.setAutoSetValues(result.auto_set_values)

            // Update domains and excluded values
            store.updateDomains(
              result.session.available_domains ?? {},
              result.excluded_values,
            )

            store.setLoading(false)
          },
          onError: () => {
            // Revert optimistic update
            store.removeSelection(characteristicSlug)
            store.setLoading(false)
            toast.error("Failed to apply selection")
          },
        },
      )
    },
    [store.sessionId, characteristics, makeSelection, store],
  )

  // ── Complete handler ──────────────────────────────────────
  const handleComplete = useCallback(() => {
    if (!store.sessionId) return

    store.setSaving(true)
    completeSession.mutate(store.sessionId, {
      onSuccess: () => {
        store.setSaving(false)
        toast.success("Configuration completed successfully")
      },
      onError: () => {
        store.setSaving(false)
        toast.error("Configuration is not yet complete")
      },
    })
  }, [store.sessionId, completeSession, store])

  // ── Loading state ─────────────────────────────────────────
  const isInitialLoading =
    productLoading || charsLoading || groupsLoading || createSession.isPending

  if (sessionError) {
    return (
      <div className="flex flex-col h-screen bg-background">
        <header className="flex items-center px-4 h-14 border-b">
          <Link
            to="/products"
            className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="text-sm">Back</span>
          </Link>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <p className="text-destructive font-medium">{sessionError}</p>
            <Button variant="outline" asChild>
              <Link to="/products">Return to Products</Link>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (isInitialLoading) {
    return (
      <div className="flex flex-col h-screen bg-background">
        <header className="flex items-center justify-between px-4 h-14 border-b">
          <div className="flex items-center gap-3">
            <Skeleton className="h-4 w-4" />
            <Skeleton className="h-5 w-48" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-8 w-24" />
          </div>
        </header>
        <div className="flex-1 flex overflow-hidden">
          {!isMobile && (
            <div className="w-[60%] flex items-center justify-center bg-muted/30 border-r">
              <Skeleton className="h-64 w-64 rounded-lg" />
            </div>
          )}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="p-4 border-b">
              <Skeleton className="h-2 w-full mb-4" />
              <div className="flex gap-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10 w-28" />
                ))}
              </div>
            </div>
            <div className="p-6 space-y-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="space-y-3">
                  <Skeleton className="h-5 w-36" />
                  <div className="grid grid-cols-2 gap-3">
                    <Skeleton className="h-20" />
                    <Skeleton className="h-20" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="h-16 border-t px-4">
          <Skeleton className="h-full w-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ── Top bar ────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 h-14 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-10 shrink-0">
        <div className="flex items-center gap-3">
          <Link
            to="/products"
            className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex flex-col">
            <h1 className="text-sm font-semibold leading-tight truncate max-w-[200px] sm:max-w-none">
              {product?.name ?? "Configurator"}
            </h1>
            {store.sessionId && (
              <span className="text-[10px] text-muted-foreground font-mono leading-tight">
                Session {store.sessionId.slice(0, 8)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="hidden sm:flex">
            <Share2 className="h-3.5 w-3.5 mr-1.5" />
            Share
          </Button>
          <Button
            size="sm"
            onClick={handleComplete}
            disabled={store.isSaving || completedSteps.size < steps.length}
          >
            {store.isSaving ? (
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5 mr-1.5" />
            )}
            Complete
          </Button>
        </div>
      </header>

      {/* ── Main content ───────────────────────────────────── */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left: Visualization */}
        {isMobile ? (
          <div className="h-48 flex items-center justify-center bg-muted/30 border-b shrink-0">
            <ProductVisualization
              productId={productId}
              selections={store.selections}
            />
          </div>
        ) : (
          <div className="hidden md:flex md:w-[60%] items-center justify-center bg-muted/30 border-r">
            <ProductVisualization
              productId={productId}
              selections={store.selections}
            />
          </div>
        )}

        {/* Right: Options panel */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Step navigation at top */}
          <StepNavigation
            steps={steps}
            currentStepIndex={currentStepIndex}
            onStepChange={setCurrentStepIndex}
            completedSteps={completedSteps}
          />

          {/* Options for current step */}
          <ScrollArea className="flex-1">
            <div className="p-6 space-y-6">
              {store.isLoading && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Applying selection...
                </div>
              )}

              {currentCharacteristics.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                  No options available for this step.
                </div>
              ) : (
                currentCharacteristics.map((char) => (
                  <OptionSelector
                    key={char.id}
                    characteristic={char}
                    selectedValue={store.selections[char.slug]}
                    excludedValues={store.excludedValues[char.slug] || []}
                    autoSetValues={store.autoSetValues}
                    onSelect={handleSelect}
                  />
                ))
              )}

              {/* Constraint feedback for current selections */}
              <ConstraintFeedback
                autoSetValues={store.autoSetValues}
                excludedValues={store.excludedValues}
                conflictExplanations={[]}
                onDismiss={() => {}}
              />

              {/* Step navigation buttons */}
              <div className="flex items-center justify-between pt-4 border-t">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setCurrentStepIndex((i) => Math.max(0, i - 1))
                  }
                  disabled={currentStepIndex === 0}
                >
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">
                  Step {currentStepIndex + 1} of {steps.length}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setCurrentStepIndex((i) =>
                      Math.min(steps.length - 1, i + 1),
                    )
                  }
                  disabled={currentStepIndex === steps.length - 1}
                >
                  Next
                </Button>
              </div>
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* ── Bottom price bar ───────────────────────────────── */}
      <PriceSummaryBar productId={productId} selections={store.selections} />
    </div>
  )
}
