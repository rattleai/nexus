import { RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Separator } from "@/components/ui/separator"
import type { ModelParameters, ParameterPreset } from "@/types/ai"

export type { ModelParameters, ParameterPreset }

export interface ModelParameterControlsProps {
  params: ModelParameters
  onChange: (params: ModelParameters) => void
  presets?: ParameterPreset[]
  className?: string
}

const DEFAULT_PARAMS: ModelParameters = {
  temperature: 1,
  topP: 1,
  maxTokens: 4096,
  frequencyPenalty: 0,
  presencePenalty: 0,
}

const DEFAULT_PRESETS: ParameterPreset[] = [
  {
    name: "Creative",
    params: { temperature: 1.5, topP: 0.95, frequencyPenalty: 0.5, presencePenalty: 0.5 },
  },
  {
    name: "Balanced",
    params: { temperature: 1, topP: 1, frequencyPenalty: 0, presencePenalty: 0 },
  },
  {
    name: "Precise",
    params: { temperature: 0.2, topP: 0.1, frequencyPenalty: 0, presencePenalty: 0 },
  },
]

interface ParameterSliderProps {
  id: string
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

function ParameterSlider({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
}: ParameterSliderProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label htmlFor={id} className="text-sm">
          {label}
        </Label>
        <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-mono tabular-nums">
          {value}
        </span>
      </div>
      <Slider
        id={id}
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        aria-label={label}
      />
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  )
}

export function ModelParameterControls({
  params,
  onChange,
  presets = DEFAULT_PRESETS,
  className,
}: ModelParameterControlsProps) {
  function updateParam<K extends keyof ModelParameters>(
    key: K,
    value: ModelParameters[K],
  ) {
    onChange({ ...params, [key]: value })
  }

  function applyPreset(preset: ParameterPreset) {
    onChange({ ...params, ...preset.params })
  }

  function resetToDefaults() {
    onChange({ ...DEFAULT_PARAMS })
  }

  return (
    <div className={cn("space-y-4", className)}>
      {presets.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Presets:
          </span>
          {presets.map((preset) => (
            <Button
              key={preset.name}
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => applyPreset(preset)}
            >
              {preset.name}
            </Button>
          ))}
        </div>
      )}

      <ParameterSlider
        id="temperature"
        label="Temperature"
        value={params.temperature}
        min={0}
        max={2}
        step={0.1}
        onChange={(v) => updateParam("temperature", v)}
      />

      <ParameterSlider
        id="topP"
        label="Top P"
        value={params.topP}
        min={0}
        max={1}
        step={0.05}
        onChange={(v) => updateParam("topP", v)}
      />

      <ParameterSlider
        id="maxTokens"
        label="Max Tokens"
        value={params.maxTokens}
        min={1}
        max={32768}
        step={1}
        onChange={(v) => updateParam("maxTokens", v)}
      />

      <ParameterSlider
        id="frequencyPenalty"
        label="Frequency Penalty"
        value={params.frequencyPenalty}
        min={-2}
        max={2}
        step={0.1}
        onChange={(v) => updateParam("frequencyPenalty", v)}
      />

      <ParameterSlider
        id="presencePenalty"
        label="Presence Penalty"
        value={params.presencePenalty}
        min={-2}
        max={2}
        step={0.1}
        onChange={(v) => updateParam("presencePenalty", v)}
      />

      <Separator />

      <Button
        variant="ghost"
        size="sm"
        className="w-full text-xs text-muted-foreground"
        onClick={resetToDefaults}
      >
        <RotateCcw className="mr-1.5 h-3 w-3" />
        Reset to defaults
      </Button>
    </div>
  )
}
