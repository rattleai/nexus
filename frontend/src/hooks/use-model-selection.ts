"use client"

import * as React from "react"
import type { AIModel } from "@/types/ai"

export type { AIModel as Model }

interface UseModelSelectionOptions {
  defaultModel?: string
  storageKey?: string
}

const DEFAULT_MODELS: AIModel[] = [
  {
    id: "gpt-4o",
    name: "GPT-4o",
    provider: "OpenAI",
    contextWindow: 128000,
    description: "Most capable OpenAI model",
  },
  {
    id: "gpt-4o-mini",
    name: "GPT-4o Mini",
    provider: "OpenAI",
    contextWindow: 128000,
    description: "Fast and affordable",
  },
  {
    id: "gpt-3.5-turbo",
    name: "GPT-3.5 Turbo",
    provider: "OpenAI",
    contextWindow: 16385,
    description: "Legacy fast model",
  },
  {
    id: "claude-sonnet-4-20250514",
    name: "Claude Sonnet 4",
    provider: "Anthropic",
    contextWindow: 200000,
    description: "Balanced performance",
  },
  {
    id: "claude-opus-4-20250514",
    name: "Claude Opus 4",
    provider: "Anthropic",
    contextWindow: 200000,
    description: "Most capable Anthropic model",
  },
  {
    id: "claude-haiku-3-5",
    name: "Claude 3.5 Haiku",
    provider: "Anthropic",
    contextWindow: 200000,
    description: "Fast and efficient",
  },
  {
    id: "gemini-pro",
    name: "Gemini Pro",
    provider: "Google",
    contextWindow: 1000000,
    description: "Large context model",
  },
]

export function useModelSelection({
  defaultModel = "gpt-4o",
  storageKey = "cadprice-selected-model",
}: UseModelSelectionOptions = {}) {
  const [models] = React.useState<AIModel[]>(DEFAULT_MODELS)
  const [isLoading] = React.useState(false)

  const [selectedModel, setSelectedModel] = React.useState<string>(() => {
    if (typeof window === "undefined") return defaultModel
    try {
      return localStorage.getItem(storageKey) ?? defaultModel
    } catch {
      return defaultModel
    }
  })

  const setModel = React.useCallback(
    (modelId: string) => {
      setSelectedModel(modelId)
      try {
        localStorage.setItem(storageKey, modelId)
      } catch {
        // localStorage not available
      }
    },
    [storageKey],
  )

  const groupedModels = React.useMemo(() => {
    const groups: Record<string, AIModel[]> = {}
    for (const model of models) {
      if (!groups[model.provider]) {
        groups[model.provider] = []
      }
      groups[model.provider].push(model)
    }
    return groups
  }, [models])

  return {
    models,
    selectedModel,
    setModel,
    isLoading,
    groupedModels,
  }
}
