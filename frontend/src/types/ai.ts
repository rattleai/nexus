// ── Shared AI/LLM types ────────────────────────────
// Single source of truth for types used across AI components, hooks, and stores.

export interface ModelParameters {
  temperature: number
  topP: number
  maxTokens: number
  frequencyPenalty: number
  presencePenalty: number
}

export type ParameterPresetName = "creative" | "balanced" | "precise"

export interface ParameterPreset {
  name: string
  params: Partial<ModelParameters>
}

export interface AIModel {
  id: string
  name: string
  provider: string
  description?: string
  contextWindow?: number
  maxOutput?: number
}

export interface TokenUsage {
  inputTokens: number
  outputTokens: number
  totalTokens: number
}

export interface PromptTemplate {
  id: string
  name: string
  description?: string
  template: string
  variables: string[]
  category?: string
  isFavorite?: boolean
}
