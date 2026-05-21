import * as React from "react"
import {
  Search,
  Trash2,
  ChevronRight,
  ChevronDown,
  Database,
  FolderOpen,
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  useDefinitionMemory,
  useDeleteDefinitionMemory,
} from "@/hooks/use-agents"
import { cn } from "@/lib/utils"

interface SharedMemoryInspectorProps {
  agentId: string
}

export function SharedMemoryInspector({ agentId }: SharedMemoryInspectorProps) {
  const { data: entries, isLoading } = useDefinitionMemory(agentId)
  const deleteMemory = useDeleteDefinitionMemory()
  const [filter, setFilter] = React.useState("")
  const [expandedKeys, setExpandedKeys] = React.useState<Set<string>>(
    new Set(),
  )
  const [collapsedNamespaces, setCollapsedNamespaces] = React.useState<
    Set<string>
  >(new Set())
  const [deletingKeys, setDeletingKeys] = React.useState<Set<string>>(
    new Set(),
  )

  const filtered = React.useMemo(() => {
    if (!entries) return []
    if (!filter) return entries
    const q = filter.toLowerCase()
    return entries.filter((e) => e.key.toLowerCase().includes(q))
  }, [entries, filter])

  const grouped = React.useMemo(() => {
    const map = new Map<string, typeof filtered>()
    for (const entry of filtered) {
      const ns = entry.namespace || "shared"
      if (!map.has(ns)) map.set(ns, [])
      map.get(ns)!.push(entry)
    }
    return map
  }, [filtered])

  const toggleExpanded = (compositeKey: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(compositeKey)) {
        next.delete(compositeKey)
      } else {
        next.add(compositeKey)
      }
      return next
    })
  }

  const toggleNamespace = (ns: string) => {
    setCollapsedNamespaces((prev) => {
      const next = new Set(prev)
      if (next.has(ns)) {
        next.delete(ns)
      } else {
        next.add(ns)
      }
      return next
    })
  }

  const handleDelete = (key: string, namespace: string) => {
    const compositeKey = `${namespace}:${key}`
    setDeletingKeys((prev) => new Set(prev).add(compositeKey))
    deleteMemory.mutate(
      { agentId, key, namespace },
      {
        onSettled: () => {
          setDeletingKeys((prev) => {
            const next = new Set(prev)
            next.delete(compositeKey)
            return next
          })
        },
      },
    )
  }

  const truncateValue = (value: Record<string, unknown>): string => {
    const json = JSON.stringify(value)
    if (json.length <= 200) return json
    return json.slice(0, 200) + "..."
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" />
          Shared Memory
          {entries && entries.length > 0 && (
            <Badge variant="secondary" className="text-xs ml-auto">
              {entries.length} {entries.length === 1 ? "entry" : "entries"}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Search filter */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by key name..."
            className="h-8 pl-8 text-xs"
          />
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Database className="h-8 w-8 text-muted-foreground/40 mb-2" />
            <p className="text-sm text-muted-foreground">
              {filter
                ? "No memory entries match your filter"
                : "No shared memory entries"}
            </p>
          </div>
        ) : (
          <ScrollArea className="max-h-[420px]">
            <div className="space-y-2">
              {Array.from(grouped.entries()).map(([namespace, nsEntries]) => (
                <Collapsible
                  key={namespace}
                  open={!collapsedNamespaces.has(namespace)}
                  onOpenChange={() => toggleNamespace(namespace)}
                >
                  <CollapsibleTrigger className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 text-xs font-medium hover:bg-accent/50 transition-colors">
                    {collapsedNamespaces.has(namespace) ? (
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    <FolderOpen className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{namespace}</span>
                    <Badge
                      variant="outline"
                      className="text-[10px] ml-auto px-1.5 py-0"
                    >
                      {nsEntries.length}
                    </Badge>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="ml-4 mt-1 space-y-1.5">
                      {nsEntries.map((entry) => {
                        const compositeKey = `${entry.namespace}:${entry.key}`
                        const isExpanded = expandedKeys.has(compositeKey)
                        const isDeleting = deletingKeys.has(compositeKey)

                        return (
                          <div
                            key={compositeKey}
                            className="rounded-md border bg-muted/30"
                          >
                            <div className="flex items-start gap-2 p-2">
                              <button
                                onClick={() => toggleExpanded(compositeKey)}
                                className="mt-0.5 shrink-0"
                              >
                                {isExpanded ? (
                                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                                )}
                              </button>
                              <div className="flex-1 min-w-0">
                                <button
                                  onClick={() => toggleExpanded(compositeKey)}
                                  className="text-left w-full"
                                >
                                  <span className="text-xs font-semibold">
                                    {entry.key}
                                  </span>
                                  {!isExpanded && (
                                    <p className="text-[11px] text-muted-foreground font-mono truncate mt-0.5">
                                      {truncateValue(entry.value)}
                                    </p>
                                  )}
                                </button>
                              </div>
                              <Button
                                variant="ghost"
                                size="sm"
                                className={cn(
                                  "h-6 w-6 p-0 shrink-0",
                                  "text-muted-foreground hover:text-destructive",
                                )}
                                disabled={isDeleting}
                                onClick={() =>
                                  handleDelete(entry.key, entry.namespace)
                                }
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                            {isExpanded && (
                              <div className="border-t px-2 py-2">
                                <pre className="text-xs font-mono bg-muted rounded p-2 overflow-x-auto max-h-60 whitespace-pre-wrap break-words">
                                  <code>
                                    {JSON.stringify(entry.value, null, 2)}
                                  </code>
                                </pre>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}
