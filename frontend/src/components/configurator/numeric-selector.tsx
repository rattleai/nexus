import { useState, useCallback, useEffect } from "react"
import { Slider } from "@/components/ui/slider"
import { Input } from "@/components/ui/input"
import type { Characteristic } from "@/types/configurator"

interface NumericSelectorProps {
  characteristic: Characteristic
  selectedValue: string | undefined
  onSelect: (value: string) => void
}

export function NumericSelector({
  characteristic,
  selectedValue,
  onSelect,
}: NumericSelectorProps) {
  const min = characteristic.numeric_min ?? 0
  const max = characteristic.numeric_max ?? 100
  const step = characteristic.numeric_step ?? 1
  const unit = characteristic.unit ?? ""

  const currentValue = selectedValue !== undefined ? Number(selectedValue) : min

  const [inputValue, setInputValue] = useState<string>(String(currentValue))

  useEffect(() => {
    setInputValue(String(currentValue))
  }, [currentValue])

  const handleSliderChange = useCallback(
    (vals: number[]) => {
      const val = vals[0]
      setInputValue(String(val))
      onSelect(String(val))
    },
    [onSelect],
  )

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value
      setInputValue(raw)
    },
    [],
  )

  const handleInputBlur = useCallback(() => {
    let parsed = Number(inputValue)
    if (Number.isNaN(parsed)) {
      parsed = currentValue
    }
    // Clamp to range
    parsed = Math.max(min, Math.min(max, parsed))
    // Snap to step
    parsed = Math.round((parsed - min) / step) * step + min
    // Avoid floating-point drift
    parsed = Number(parsed.toFixed(10))

    setInputValue(String(parsed))
    onSelect(String(parsed))
  }, [inputValue, currentValue, min, max, step, onSelect])

  const handleInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        handleInputBlur()
      }
    },
    [handleInputBlur],
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <Slider
            min={min}
            max={max}
            step={step}
            value={[currentValue]}
            onValueChange={handleSliderChange}
          />
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={min}
            max={max}
            step={step}
            value={inputValue}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
            onKeyDown={handleInputKeyDown}
            className="w-24 text-right tabular-nums"
          />
          {unit && (
            <span className="text-sm text-muted-foreground whitespace-nowrap">
              {unit}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {min}
          {unit ? ` ${unit}` : ""}
        </span>
        {step !== 1 && (
          <span className="text-muted-foreground/70">Step: {step}{unit ? ` ${unit}` : ""}</span>
        )}
        <span>
          {max}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
    </div>
  )
}
