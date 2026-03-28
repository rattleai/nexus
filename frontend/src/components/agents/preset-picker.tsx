import * as React from "react"
import {
  ShieldCheck,
  Eye,
  Wrench,
  DollarSign,
  Code,
  Shield,
  Check,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { CapabilityPreset } from "@/types/agents"

const PRESET_ICONS: Record<string, React.ElementType> = {
  ShieldCheck,
  Eye,
  Wrench,
  DollarSign,
  Code,
  Shield,
}

interface PresetPickerProps {
  presets: CapabilityPreset[] | undefined
  isLoading?: boolean
  onApply: (preset: CapabilityPreset) => void
  activeCapabilities?: string[]
}

export function PresetPicker({
  presets,
  isLoading,
  onApply,
  activeCapabilities = [],
}: PresetPickerProps) {
  if (isLoading || !presets) {
    return (
      <div className="grid grid-cols-2 gap-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-20 rounded-lg border bg-muted/30 animate-pulse" />
        ))}
      </div>
    )
  }

  if (presets.length === 0) return null

  const activeSet = new Set(activeCapabilities)

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Quick presets</p>
      <div className="grid grid-cols-2 gap-2">
        {presets.map((preset) => {
          const Icon = PRESET_ICONS[preset.icon] ?? Shield
          const isMatch =
            preset.capabilities.length > 0 &&
            preset.capabilities.every((c) => activeSet.has(c)) &&
            activeSet.size === preset.capabilities.length

          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => onApply(preset)}
              className={cn(
                "flex items-start gap-2.5 rounded-lg border p-3 text-left transition-colors",
                isMatch
                  ? "border-primary ring-2 ring-primary/20 bg-accent/30"
                  : "hover:bg-accent/50"
              )}
            >
              <Icon className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-medium truncate">{preset.name}</span>
                  {isMatch && <Check className="h-3 w-3 text-primary shrink-0" />}
                </div>
                <p className="text-[10px] text-muted-foreground line-clamp-2 mt-0.5">
                  {preset.description}
                </p>
                <span className="text-[10px] text-muted-foreground mt-1 block">
                  {preset.capabilities.length} capabilities
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
