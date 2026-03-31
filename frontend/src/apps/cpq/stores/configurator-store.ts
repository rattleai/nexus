import { create } from "zustand"

interface PriceSummary {
  base_price: number
  total_adjustments: number
  final_price: number
  currency: string
  breakdown: Record<string, unknown>[]
}

interface ConfiguratorState {
  // Session context
  sessionId: string | null
  productId: string | null
  productName: string | null

  // Selections (optimistic, updated before server confirms)
  selections: Record<string, string>
  autoSetValues: Record<string, string>

  // Domains (from last propagation)
  availableDomains: Record<string, unknown>
  excludedValues: Record<string, string[]>

  // UI state
  currentStepIndex: number
  stepSlugs: string[]
  isLoading: boolean
  isSaving: boolean

  // Price
  priceSummary: PriceSummary | null

  // Comparison mode
  comparisonSessionIds: string[]

  // Actions
  setSession: (sessionId: string, productId: string, productName: string) => void
  setSelection: (charSlug: string, value: string) => void
  removeSelection: (charSlug: string) => void
  setAutoSetValues: (values: Record<string, string>) => void
  updateDomains: (domains: Record<string, unknown>, excluded: Record<string, string[]>) => void
  applySelectionResult: (selections: Record<string, string>, autoSetValues: Record<string, string>, domains: Record<string, unknown>, excluded: Record<string, string[]>) => void
  setCurrentStep: (index: number) => void
  setStepSlugs: (slugs: string[]) => void
  setPriceSummary: (summary: PriceSummary | null) => void
  setLoading: (loading: boolean) => void
  setSaving: (saving: boolean) => void
  toggleComparisonSession: (sessionId: string) => void
  reset: () => void
}

const initialState = {
  sessionId: null as string | null,
  productId: null as string | null,
  productName: null as string | null,
  selections: {} as Record<string, string>,
  autoSetValues: {} as Record<string, string>,
  availableDomains: {} as Record<string, unknown>,
  excludedValues: {} as Record<string, string[]>,
  currentStepIndex: 0,
  stepSlugs: [] as string[],
  isLoading: false,
  isSaving: false,
  priceSummary: null as PriceSummary | null,
  comparisonSessionIds: [] as string[],
}

export const useConfiguratorStore = create<ConfiguratorState>((set) => ({
  ...initialState,

  setSession: (sessionId, productId, productName) =>
    set({ sessionId, productId, productName }),

  setSelection: (charSlug, value) =>
    set((state) => ({
      selections: { ...state.selections, [charSlug]: value },
    })),

  removeSelection: (charSlug) =>
    set((state) => {
      const { [charSlug]: _removed, ...rest } = state.selections
      return { selections: rest }
    }),

  setAutoSetValues: (values) => set({ autoSetValues: values }),

  updateDomains: (domains, excluded) =>
    set({ availableDomains: domains, excludedValues: excluded }),

  applySelectionResult: (selections, autoSetValues, domains, excluded) =>
    set({
      selections,
      autoSetValues,
      availableDomains: domains,
      excludedValues: excluded,
      isLoading: false,
    }),

  setCurrentStep: (index) => set({ currentStepIndex: index }),

  setStepSlugs: (slugs) => set({ stepSlugs: slugs }),

  setPriceSummary: (summary) => set({ priceSummary: summary }),

  setLoading: (loading) => set({ isLoading: loading }),

  setSaving: (saving) => set({ isSaving: saving }),

  toggleComparisonSession: (sessionId) =>
    set((state) => {
      const ids = state.comparisonSessionIds
      if (ids.includes(sessionId)) {
        return { comparisonSessionIds: ids.filter((id) => id !== sessionId) }
      }
      if (ids.length >= 3) return state // max 3
      return { comparisonSessionIds: [...ids, sessionId] }
    }),

  reset: () => set(initialState),
}))
