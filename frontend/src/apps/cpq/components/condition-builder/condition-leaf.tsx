import { memo, useCallback, useMemo } from "react"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { MultiSelect } from "@/components/multi-select"
import type { Characteristic } from "@/apps/cpq/types/configurator"
import type { LeafCondition, LeafOperator } from "./condition-types"
import { getOperatorsForType, getOperatorLabel } from "./condition-utils"

interface ConditionLeafProps {
  condition: LeafCondition
  characteristics: Characteristic[]
  onChange: (condition: LeafCondition) => void
  onDelete: () => void
}

export const ConditionLeaf = memo(function ConditionLeaf({
  condition,
  characteristics,
  onChange,
  onDelete,
}: ConditionLeafProps) {
  const selectedChar = useMemo(
    () => characteristics.find((c) => c.slug === condition.char),
    [characteristics, condition.char],
  )

  const availableOperators = useMemo(
    () => getOperatorsForType(selectedChar?.char_type ?? "text"),
    [selectedChar?.char_type],
  )

  const handleCharChange = useCallback(
    (slug: string) => {
      const char = characteristics.find((c) => c.slug === slug)
      const operators = getOperatorsForType(char?.char_type ?? "text")
      const newOp = operators.includes(condition.op) ? condition.op : operators[0]

      // Reset value to appropriate default
      let defaultValue: LeafCondition["value"] = ""
      if (char?.char_type === "boolean") {
        defaultValue = "true"
      } else if (
        char?.char_type === "numeric" &&
        newOp === "between"
      ) {
        defaultValue = [0, 0]
      } else if (newOp === "in" || newOp === "not_in") {
        defaultValue = []
      }

      onChange({ char: slug, op: newOp, value: defaultValue })
    },
    [characteristics, condition.op, onChange],
  )

  const handleOpChange = useCallback(
    (newOp: LeafOperator) => {
      let newValue: LeafCondition["value"] = condition.value

      // Adapt value shape when switching operator categories
      if (newOp === "between") {
        if (!Array.isArray(newValue) || newValue.length !== 2) {
          const num =
            typeof newValue === "number"
              ? newValue
              : typeof newValue === "string"
                ? parseFloat(newValue) || 0
                : 0
          newValue = [num, num]
        }
      } else if (newOp === "in" || newOp === "not_in") {
        if (!Array.isArray(newValue)) {
          newValue = newValue !== "" ? [String(newValue)] : []
        }
      } else {
        // Single-value operator
        if (Array.isArray(newValue)) {
          newValue = newValue.length > 0 ? String(newValue[0]) : ""
        }
      }

      onChange({ ...condition, op: newOp, value: newValue })
    },
    [condition, onChange],
  )

  const handleValueChange = useCallback(
    (value: LeafCondition["value"]) => {
      onChange({ ...condition, value })
    },
    [condition, onChange],
  )

  return (
    <div className="flex items-center gap-2">
      {/* Characteristic Select */}
      <Select value={condition.char} onValueChange={handleCharChange}>
        <SelectTrigger className="w-[180px] h-9 text-sm">
          <SelectValue placeholder="Select field..." />
        </SelectTrigger>
        <SelectContent>
          {characteristics.map((char) => (
            <SelectItem key={char.slug} value={char.slug}>
              {char.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Operator Select */}
      <Select
        value={condition.op}
        onValueChange={(v) => handleOpChange(v as LeafOperator)}
      >
        <SelectTrigger className="w-[130px] h-9 text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {availableOperators.map((op) => (
            <SelectItem key={op} value={op}>
              {getOperatorLabel(op)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Value Input - adapts by char_type and operator */}
      <ValueInput
        condition={condition}
        characteristic={selectedChar ?? null}
        onChange={handleValueChange}
      />

      {/* Delete button */}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
        onClick={onDelete}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  )
})

// ── Value input sub-component ──────────────────────────────────

interface ValueInputProps {
  condition: LeafCondition
  characteristic: Characteristic | null
  onChange: (value: LeafCondition["value"]) => void
}

function ValueInput({ condition, characteristic, onChange }: ValueInputProps) {
  const { op, value } = condition
  const charType = characteristic?.char_type ?? "text"

  // enum + in/not_in: MultiSelect
  if (charType === "enum" && (op === "in" || op === "not_in")) {
    const options = (characteristic?.values ?? []).map((v) => ({
      value: v.value,
      label: v.label,
    }))
    const selected = Array.isArray(value) ? value.map(String) : []

    return (
      <div className="min-w-[200px] flex-1">
        <MultiSelect
          options={options}
          selected={selected}
          onChange={(vals) => onChange(vals)}
          placeholder="Select values..."
          className="h-9"
        />
      </div>
    )
  }

  // enum + eq/neq: Single select from char.values
  if (charType === "enum" && (op === "eq" || op === "neq")) {
    return (
      <Select
        value={typeof value === "string" ? value : ""}
        onValueChange={(v) => onChange(v)}
      >
        <SelectTrigger className="w-[180px] h-9 text-sm">
          <SelectValue placeholder="Select value..." />
        </SelectTrigger>
        <SelectContent>
          {(characteristic?.values ?? []).map((v) => (
            <SelectItem key={v.value} value={v.value}>
              {v.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  // boolean: Select true/false
  if (charType === "boolean") {
    return (
      <Select
        value={typeof value === "string" ? value : String(value)}
        onValueChange={(v) => onChange(v)}
      >
        <SelectTrigger className="w-[130px] h-9 text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">True</SelectItem>
          <SelectItem value="false">False</SelectItem>
        </SelectContent>
      </Select>
    )
  }

  // numeric + between: two number inputs
  if (charType === "numeric" && op === "between") {
    const pair = Array.isArray(value) && value.length === 2 ? value : [0, 0]

    return (
      <div className="flex items-center gap-1.5">
        <Input
          type="number"
          className="w-[100px] h-9 text-sm"
          value={pair[0] ?? ""}
          min={characteristic?.numeric_min ?? undefined}
          max={characteristic?.numeric_max ?? undefined}
          step={characteristic?.numeric_step ?? undefined}
          onChange={(e) => {
            const num = e.target.value === "" ? 0 : Number(e.target.value)
            onChange([num, pair[1]] as [number, number])
          }}
        />
        <span className="text-xs text-muted-foreground">to</span>
        <Input
          type="number"
          className="w-[100px] h-9 text-sm"
          value={pair[1] ?? ""}
          min={characteristic?.numeric_min ?? undefined}
          max={characteristic?.numeric_max ?? undefined}
          step={characteristic?.numeric_step ?? undefined}
          onChange={(e) => {
            const num = e.target.value === "" ? 0 : Number(e.target.value)
            onChange([pair[0], num] as [number, number])
          }}
        />
      </div>
    )
  }

  // numeric (single op): number input
  if (charType === "numeric") {
    const numVal =
      typeof value === "number"
        ? value
        : typeof value === "string"
          ? value
          : ""

    return (
      <Input
        type="number"
        className="w-[150px] h-9 text-sm"
        value={numVal}
        min={characteristic?.numeric_min ?? undefined}
        max={characteristic?.numeric_max ?? undefined}
        step={characteristic?.numeric_step ?? undefined}
        onChange={(e) => {
          onChange(e.target.value === "" ? "" : Number(e.target.value))
        }}
      />
    )
  }

  // text (default): text input
  return (
    <Input
      type="text"
      className="w-[200px] h-9 text-sm"
      placeholder="Enter value..."
      value={typeof value === "string" ? value : String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}
