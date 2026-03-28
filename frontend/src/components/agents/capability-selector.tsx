import * as React from "react"
import {
  Package,
  Cpu,
  ChevronDown,
  ChevronRight,
  Shield,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Info,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { CapabilityCatalog, CapabilityDomain, ToolCapability } from "@/types/agents"

const DOMAIN_ICONS: Record<string, React.ElementType> = {
  cpq: Package,
  platform: Cpu,
}

const RISK_CONFIG = {
  low: { label: "Low", className: "border-green-500/50 text-green-600 dark:text-green-400" },
  medium: { label: "Medium", className: "border-yellow-500/50 text-yellow-600 dark:text-yellow-400" },
  high: { label: "High", className: "border-orange-500/50 text-orange-600 dark:text-orange-400" },
  critical: { label: "Critical", className: "border-red-500/50 text-red-600 dark:text-red-400" },
} as const

interface CapabilitySelectorProps {
  capabilities: string[]
  onChange: (capabilities: string[]) => void
  catalog: CapabilityCatalog | undefined
  isLoading?: boolean
}

export function CapabilitySelector({
  capabilities,
  onChange,
  catalog,
  isLoading,
}: CapabilitySelectorProps) {
  const [expandedDomains, setExpandedDomains] = React.useState<Set<string>>(new Set())
  const [showTools, setShowTools] = React.useState<Set<string>>(new Set())

  if (isLoading || !catalog) {
    return (
      <div className="space-y-3">
        {[1, 2].map((i) => (
          <div key={i} className="h-16 rounded-lg border bg-muted/30 animate-pulse" />
        ))}
      </div>
    )
  }

  if (catalog.domains.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No capabilities available. Install a plugin to add capability domains.
      </p>
    )
  }

  const selectedSet = new Set(capabilities)

  const toggleCapability = (slug: string) => {
    const next = new Set(selectedSet)
    if (next.has(slug)) {
      next.delete(slug)
    } else {
      next.add(slug)
    }
    onChange([...next])
  }

  const toggleDomain = (domain: CapabilityDomain) => {
    const domainSlugs = domain.capabilities.map((c) => c.slug)
    const allSelected = domainSlugs.every((s) => selectedSet.has(s))
    const next = new Set(selectedSet)
    if (allSelected) {
      domainSlugs.forEach((s) => next.delete(s))
    } else {
      domainSlugs.forEach((s) => next.add(s))
    }
    onChange([...next])
  }

  const toggleExpandDomain = (slug: string) => {
    setExpandedDomains((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  const toggleShowTools = (slug: string) => {
    setShowTools((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  return (
    <TooltipProvider delayDuration={300}>
    <div className="space-y-3">
      {catalog.domains.map((domain) => {
        const DomainIcon = DOMAIN_ICONS[domain.slug] ?? Package
        const domainSlugs = domain.capabilities.map((c) => c.slug)
        const selectedCount = domainSlugs.filter((s) => selectedSet.has(s)).length
        const allSelected = selectedCount === domainSlugs.length
        const someSelected = selectedCount > 0 && !allSelected
        const isExpanded = expandedDomains.has(domain.slug)
        const totalTools = domain.capabilities.reduce((sum, c) => sum + c.tool_count, 0)

        return (
          <Card key={domain.slug} className={cn(someSelected || allSelected ? "border-primary/40" : "")}>
            <CardHeader className="p-4 pb-0">
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  className="flex items-center gap-2.5 text-left flex-1"
                  onClick={() => toggleExpandDomain(domain.slug)}
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  )}
                  <DomainIcon className="h-4 w-4 shrink-0" />
                  <span className="text-sm font-medium">{domain.label}</span>
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    {selectedCount}/{domain.capabilities.length}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground">
                    {totalTools} tools
                  </span>
                </button>
                <Switch
                  checked={allSelected}
                  onCheckedChange={() => toggleDomain(domain)}
                  aria-label={`Toggle all ${domain.label} capabilities`}
                />
              </div>
            </CardHeader>

            {isExpanded && (
              <CardContent className="p-4 pt-3">
                <div className="space-y-1">
                  {domain.capabilities.map((cap) => (
                    <CapabilityRow
                      key={cap.slug}
                      capability={cap}
                      selected={selectedSet.has(cap.slug)}
                      onToggle={() => toggleCapability(cap.slug)}
                      showingTools={showTools.has(cap.slug)}
                      onToggleTools={() => toggleShowTools(cap.slug)}
                    />
                  ))}
                </div>
              </CardContent>
            )}
          </Card>
        )
      })}
    </div>
    </TooltipProvider>
  )
}

function CapabilityRow({
  capability,
  selected,
  onToggle,
  showingTools,
  onToggleTools,
}: {
  capability: ToolCapability
  selected: boolean
  onToggle: () => void
  showingTools: boolean
  onToggleTools: () => void
}) {
  const risk = RISK_CONFIG[capability.risk_level] ?? RISK_CONFIG.low

  return (
    <div className={cn("rounded-md border px-3 py-2 transition-colors", selected ? "bg-accent/30" : "")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Switch
            checked={selected}
            onCheckedChange={onToggle}
            aria-label={capability.label}
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium truncate">{capability.label}</span>
              <Badge variant="outline" className={cn("text-[10px] px-1 py-0", risk.className)}>
                {risk.label}
              </Badge>
              {capability.requires_approval_default && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <ShieldAlert className="h-3.5 w-3.5 text-yellow-500 shrink-0" />
                  </TooltipTrigger>
                  <TooltipContent>Requires approval by default</TooltipContent>
                </Tooltip>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground truncate">{capability.description}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onToggleTools}
          className="text-[10px] text-muted-foreground hover:text-foreground whitespace-nowrap"
        >
          {capability.tool_count} tools {showingTools ? "^" : "v"}
        </button>
      </div>

      {showingTools && (
        <div className="mt-2 flex flex-wrap gap-1 pl-10">
          {capability.tools.map((tool) => (
            <Badge key={tool} variant="outline" className="text-[10px] font-mono px-1.5 py-0">
              {tool}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
