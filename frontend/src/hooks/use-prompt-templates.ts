import { useCallback, useState } from "react"
import type { PromptTemplate } from "@/types/ai"

const STORAGE_KEY = "prompt-templates"

function extractVariables(template: string): string[] {
  const matches = template.match(/\{\{(\w+)\}\}/g)
  if (!matches) return []
  return [...new Set(matches.map((m) => m.slice(2, -2)))]
}

function loadTemplates(): PromptTemplate[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function saveTemplates(templates: PromptTemplate[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(templates))
}

export function usePromptTemplates() {
  const [templates, setTemplates] = useState<PromptTemplate[]>(loadTemplates)

  const persist = useCallback((updated: PromptTemplate[]) => {
    setTemplates(updated)
    saveTemplates(updated)
  }, [])

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
      persist([...templates, newTemplate])
      return newTemplate
    },
    [templates, persist],
  )

  const updateTemplate = useCallback(
    (id: string, updates: Partial<Pick<PromptTemplate, "name" | "template" | "category">>) => {
      persist(
        templates.map((t) =>
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
    [templates, persist],
  )

  const deleteTemplate = useCallback(
    (id: string) => {
      persist(templates.filter((t) => t.id !== id))
    },
    [templates, persist],
  )

  const toggleFavorite = useCallback(
    (id: string) => {
      persist(
        templates.map((t) =>
          t.id === id ? { ...t, isFavorite: !t.isFavorite } : t,
        ),
      )
    },
    [templates, persist],
  )

  const compileTemplate = useCallback(
    (templateId: string, values: Record<string, string>) => {
      const tmpl = templates.find((t) => t.id === templateId)
      if (!tmpl) return ""
      return tmpl.template.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key] ?? `{{${key}}}`)
    },
    [templates],
  )

  const categories = [...new Set(templates.map((t) => t.category).filter(Boolean))] as string[]

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
