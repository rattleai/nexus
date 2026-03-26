import type { Characteristic, CharacteristicValue } from "@/types/configurator"
import { OptionSwatch } from "./option-swatch"
import { OptionCard } from "./option-card"
import { NumericSelector } from "./numeric-selector"
import { BooleanSelector } from "./boolean-selector"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Zap } from "lucide-react"

interface OptionSelectorProps {
  characteristic: Characteristic
  selectedValue: string | undefined
  excludedValues: string[]
  autoSetValues: Record<string, string>
  onSelect: (characteristicId: string, charSlug: string, value: string) => void
}

function hasImages(characteristic: Characteristic): boolean {
  return characteristic.values.some(
    (v: CharacteristicValue) => v.image_url !== null && v.image_url !== "",
  )
}

export function OptionSelector({
  characteristic,
  selectedValue,
  excludedValues,
  autoSetValues,
  onSelect,
}: OptionSelectorProps) {
  const isAutoSet = characteristic.slug in autoSetValues

  const handleSelect = (value: string) => {
    onSelect(characteristic.id, characteristic.slug, value)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Label className="text-base font-semibold">{characteristic.name}</Label>
        {characteristic.is_required && (
          <Badge variant="outline" className="text-xs">
            Required
          </Badge>
        )}
        {isAutoSet && (
          <Badge variant="secondary" className="text-xs gap-1">
            <Zap className="h-3 w-3" /> Auto-selected
          </Badge>
        )}
      </div>

      {characteristic.description && (
        <p className="text-sm text-muted-foreground">
          {characteristic.description}
        </p>
      )}

      {/* Enum: use swatches if values have images, otherwise cards */}
      {characteristic.char_type === "enum" &&
        (hasImages(characteristic) ? (
          <OptionSwatch
            values={characteristic.values}
            selectedValue={selectedValue}
            excludedValues={excludedValues}
            onSelect={handleSelect}
          />
        ) : (
          <OptionCard
            values={characteristic.values}
            selectedValue={selectedValue}
            excludedValues={excludedValues}
            isMultiSelect={characteristic.is_multi_select}
            onSelect={handleSelect}
          />
        ))}

      {/* Numeric: slider + input */}
      {characteristic.char_type === "numeric" && (
        <NumericSelector
          characteristic={characteristic}
          selectedValue={selectedValue}
          onSelect={handleSelect}
        />
      )}

      {/* Boolean: toggle card */}
      {characteristic.char_type === "boolean" && (
        <BooleanSelector
          characteristic={characteristic}
          selectedValue={selectedValue}
          onSelect={handleSelect}
        />
      )}

      {/* Text: free-form input */}
      {characteristic.char_type === "text" && (
        <Input
          type="text"
          value={selectedValue ?? ""}
          placeholder={`Enter ${characteristic.name.toLowerCase()}...`}
          onChange={(e) => handleSelect(e.target.value)}
        />
      )}
    </div>
  )
}
