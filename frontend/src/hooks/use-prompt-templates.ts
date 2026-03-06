import { useCallback, useMemo, useState } from "react"
import type { PromptTemplate } from "@/types/ai"

const STORAGE_KEY = "prompt-templates"

function extractVariables(template: string): string[] {
  const matches = template.match(/\{\{(\w+)\}\}/g)
  if (!matches) return []
  return [...new Set(matches.map((m) => m.slice(2, -2)))]
}

function loadTemplates(): PromptTemplate[] {
  if (typeof window === "undefined") return []
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function saveTemplates(templates: PromptTemplate[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(templates))
  } catch {
    // localStorage not available or quota exceeded
  }
}

export function usePromptTemplates() {
  const [templates, setTemplates] = useState<PromptTemplate[]>(loadTemplates)

  const persist = useCallback(
    (updater: (prev: PromptTemplate[]) => PromptTemplate[]) => {
      setTemplates((prev) => {
        const updated = updater(prev)
        saveTemplates(updated)
        return updated
      })
    },
    [],
  )

  const addTemplate = useCallback(
    (name: string, template: string, category?: string) => {
      const newTemplate: PromptTemplate = {
        id: crypto.randomUUID(),
        name,
        template,
        variables: extractVariables(template),
        category,
        isFavorite: false,
      }
      persist((prev) => [...prev, newTemplate])
      return newTemplate
    },
    [persist],
  )

  const updateTemplate = useCallback(
    (id: string, updates: Partial<Pick<PromptTemplate, "name" | "template" | "category">>) => {
      persist((prev) =>
        prev.map((t) =>
          t.id === id
            ? {
                ...t,
                ...updates,
                variables: updates.template
                  ? extractVariables(updates.template)
                  : t.variables,
              }
            : t,
        ),
      )
    },
    [persist],
  )

  const deleteTemplate = useCallback(
    (id: string) => {
      persist((prev) => prev.filter((t) => t.id !== id))
    },
    [persist],
  )

  const toggleFavorite = useCallback(
    (id: string) => {
      persist((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, isFavorite: !t.isFavorite } : t,
        ),
      )
    },
    [persist],
  )

  const compileTemplate = useCallback(
    (templateId: string, values: Record<string, string>) => {
      const tmpl = templates.find((t) => t.id === templateId)
      if (!tmpl) return ""
      return tmpl.template.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key] ?? `{{${key}}}`)
    },
    [templates],
  )

  const categories = useMemo(
    () => [...new Set(templates.map((t) => t.category).filter(Boolean))] as string[],
    [templates],
  )

  return {
    templates,
    addTemplate,
    updateTemplate,
    deleteTemplate,
    toggleFavorite,
    compileTemplate,
    categories,
  }
}
