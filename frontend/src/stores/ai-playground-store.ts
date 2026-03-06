import { create } from "zustand"
import { persist } from "zustand/middleware"

// ── Types ────────────────────────────────────────────

export interface ModelParameters {
  temperature: number
  topP: number
  maxTokens: number
  frequencyPenalty: number
  presencePenalty: number
}

export type ParameterPreset = "creative" | "balanced" | "precise"

export interface PlaygroundResponse {
  id: string
  model: string
  prompt: string
  response: string
  parameters: ModelParameters
  tokenUsage: {
    promptTokens: number
    completionTokens: number
    totalTokens: number
  } | null
  durationMs: number | null
  createdAt: string
}

// ── Presets ───────────────────────────────────────────

const PARAMETER_PRESETS: Record<ParameterPreset, ModelParameters> = {
  creative: {
    temperature: 1.2,
    topP: 0.95,
    maxTokens: 2048,
    frequencyPenalty: 0.3,
    presencePenalty: 0.6,
  },
  balanced: {
    temperature: 0.7,
    topP: 1.0,
    maxTokens: 1024,
    frequencyPenalty: 0.0,
    presencePenalty: 0.0,
  },
  precise: {
    temperature: 0.2,
    topP: 0.5,
    maxTokens: 512,
    frequencyPenalty: 0.5,
    presencePenalty: 0.0,
  },
}

const DEFAULT_PARAMETERS: ModelParameters = { ...PARAMETER_PRESETS.balanced }

// ── State ────────────────────────────────────────────

interface AIPlaygroundState {
  parameters: ModelParameters
  comparisonMode: boolean
  comparisonModels: string[]
  responseHistory: PlaygroundResponse[]

  setParameter: <K extends keyof ModelParameters>(
    key: K,
    value: ModelParameters[K],
  ) => void
  resetParameters: () => void
  toggleComparisonMode: () => void
  addComparisonModel: (model: string) => void
  removeComparisonModel: (model: string) => void
  setPreset: (preset: ParameterPreset) => void
  addResponse: (response: Omit<PlaygroundResponse, "id" | "createdAt">) => void
  clearHistory: () => void
}

export const useAIPlaygroundStore = create<AIPlaygroundState>()(
  persist(
    (set) => ({
      parameters: { ...DEFAULT_PARAMETERS },
      comparisonMode: false,
      comparisonModels: [],
      responseHistory: [],

      setParameter: (key, value) =>
        set((s) => ({
          parameters: { ...s.parameters, [key]: value },
        })),

      resetParameters: () => set({ parameters: { ...DEFAULT_PARAMETERS } }),

      toggleComparisonMode: () =>
        set((s) => ({ comparisonMode: !s.comparisonMode })),

      addComparisonModel: (model) =>
        set((s) => {
          if (s.comparisonModels.includes(model)) return s
          return { comparisonModels: [...s.comparisonModels, model] }
        }),

      removeComparisonModel: (model) =>
        set((s) => ({
          comparisonModels: s.comparisonModels.filter((m) => m !== model),
        })),

      setPreset: (preset) =>
        set({ parameters: { ...PARAMETER_PRESETS[preset] } }),

      addResponse: (response) =>
        set((s) => ({
          responseHistory: [
            {
              ...response,
              id: crypto.randomUUID(),
              createdAt: new Date().toISOString(),
            },
            ...s.responseHistory,
          ],
        })),

      clearHistory: () => set({ responseHistory: [] }),
    }),
    {
      name: "ai-playground-store",
      partialize: (s) => ({
        parameters: s.parameters,
        comparisonModels: s.comparisonModels,
        responseHistory: s.responseHistory.slice(0, 50),
      }),
    },
  ),
)
