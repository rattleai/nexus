import { useState, useMemo } from "react"
import { Search, Star, Variable } from "lucide-react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { PromptTemplate } from "@/types/ai"

export type { PromptTemplate }

export interface PromptTemplateLibraryProps {
  templates: PromptTemplate[]
  onSelect: (template: PromptTemplate) => void
  onToggleFavorite?: (id: string) => void
  className?: string
}

function highlightVariables(template: string): React.ReactNode {
  const parts = template.split(/(\{\{[^}]+\}\})/g)
  return parts.map((part, i) => {
    if (part.startsWith("{{") && part.endsWith("}}")) {
      return (
        <span
          key={i}
          className="rounded bg-primary/10 px-0.5 font-medium text-primary"
        >
          {part}
        </span>
      )
    }
    return part
  })
}

function TemplateCard({
  template,
  onSelect,
  onToggleFavorite,
}: {
  template: PromptTemplate
  onSelect: (template: PromptTemplate) => void
  onToggleFavorite?: (id: string) => void
}) {
  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-accent/50"
      onClick={() => onSelect(template)}
      role="button"
      tabIndex={0}
      aria-label={`Select template: ${template.name}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onSelect(template)
        }
      }}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h4 className="truncate text-sm font-medium">{template.name}</h4>
            {template.description && (
              <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                {template.description}
              </p>
            )}
          </div>
          {onToggleFavorite && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 shrink-0 p-0"
              onClick={(e) => {
                e.stopPropagation()
                onToggleFavorite(template.id)
              }}
              aria-label={
                template.isFavorite
                  ? `Remove ${template.name} from favorites`
                  : `Add ${template.name} to favorites`
              }
            >
              <Star
                className={cn(
                  "h-4 w-4",
                  template.isFavorite
                    ? "fill-amber-400 text-amber-400"
                    : "text-muted-foreground",
                )}
              />
            </Button>
          )}
        </div>

        <div className="mt-3 rounded-md bg-muted/50 p-2">
          <p className="text-xs leading-relaxed text-muted-foreground line-clamp-3">
            {highlightVariables(template.template)}
          </p>
        </div>

        {template.variables.length > 0 && (
          <div className="mt-2 flex items-center gap-1.5">
            <Variable className="h-3 w-3 text-muted-foreground" />
            <div className="flex flex-wrap gap-1">
              {template.variables.map((v) => (
                <Badge
                  key={v}
                  variant="secondary"
                  className="px-1.5 py-0 text-[10px]"
                >
                  {v}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function PromptTemplateLibrary({
  templates,
  onSelect,
  onToggleFavorite,
  className,
}: PromptTemplateLibraryProps) {
  const [search, setSearch] = useState("")

  const categories = useMemo(() => {
    const cats = new Set<string>()
    for (const t of templates) {
      if (t.category) cats.add(t.category)
    }
    return ["all", ...Array.from(cats)]
  }, [templates])

  const filteredBySearch = useMemo(() => {
    if (!search) return templates
    const q = search.toLowerCase()
    return templates.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q) ||
        t.template.toLowerCase().includes(q),
    )
  }, [templates, search])

  function getFilteredTemplates(category: string) {
    if (category === "all") return filteredBySearch
    return filteredBySearch.filter((t) => t.category === category)
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search templates..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
          aria-label="Search prompt templates"
        />
      </div>

      <Tabs defaultValue="all">
        <TabsList className="w-full justify-start overflow-x-auto">
          {categories.map((cat) => (
            <TabsTrigger key={cat} value={cat} className="text-xs capitalize">
              {cat}
            </TabsTrigger>
          ))}
        </TabsList>

        {categories.map((cat) => (
          <TabsContent key={cat} value={cat}>
            <ScrollArea className="h-[400px]">
              <div className="grid grid-cols-1 gap-3 pr-4 sm:grid-cols-2">
                {getFilteredTemplates(cat).length === 0 ? (
                  <p className="col-span-full py-8 text-center text-sm text-muted-foreground">
                    No templates found.
                  </p>
                ) : (
                  getFilteredTemplates(cat).map((template) => (
                    <TemplateCard
                      key={template.id}
                      template={template}
                      onSelect={onSelect}
                      onToggleFavorite={onToggleFavorite}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
