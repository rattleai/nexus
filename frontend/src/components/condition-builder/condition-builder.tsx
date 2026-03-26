import { useCallback } from "react"
import { Plus, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Characteristic } from "@/types/configurator"
import type {
  ConditionNode,
  CompoundCondition,
  LeafCondition,
} from "./condition-types"
import { isLeafCondition, isCompoundCondition } from "./condition-types"
import { createEmptyLeaf, createEmptyGroup } from "./condition-utils"
import { ConditionLeaf } from "./condition-leaf"
import { ConditionGroup } from "./condition-group"

export interface ConditionBuilderProps {
  value: ConditionNode | null
  onChange: (value: ConditionNode | null) => void
  characteristics: Characteristic[]
  className?: string
}

export function ConditionBuilder({
  value,
  onChange,
  characteristics,
  className,
}: ConditionBuilderProps) {
  const handleAddCondition = useCallback(() => {
    if (value === null) {
      // First condition: create a standalone leaf
      onChange(createEmptyLeaf())
      return
    }

    if (isLeafCondition(value)) {
      // Second condition: auto-wrap both in an AND group
      onChange({
        op: "and",
        conditions: [value, createEmptyLeaf()],
      } satisfies CompoundCondition)
      return
    }

    if (isCompoundCondition(value)) {
      // Already a group: append new leaf
      onChange({
        ...value,
        conditions: [...value.conditions, createEmptyLeaf()],
      })
    }
  }, [value, onChange])

  const handleClear = useCallback(() => {
    onChange(null)
  }, [onChange])

  const handleLeafChange = useCallback(
    (updated: LeafCondition) => {
      onChange(updated)
    },
    [onChange],
  )

  const handleLeafDelete = useCallback(() => {
    onChange(null)
  }, [onChange])

  const handleGroupChange = useCallback(
    (updated: CompoundCondition) => {
      // If the group is reduced to a single leaf, unwrap it
      if (updated.conditions.length === 1 && isLeafCondition(updated.conditions[0])) {
        onChange(updated.conditions[0])
        return
      }
      // If group becomes empty, clear
      if (updated.conditions.length === 0) {
        onChange(null)
        return
      }
      onChange(updated)
    },
    [onChange],
  )

  const handleGroupDelete = useCallback(() => {
    onChange(null)
  }, [onChange])

  return (
    <div className={cn("space-y-3", className)}>
      {/* Empty state */}
      {value === null && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 text-xs border-dashed"
          onClick={handleAddCondition}
        >
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          Add condition
        </Button>
      )}

      {/* Single leaf */}
      {value !== null && isLeafCondition(value) && (
        <div className="space-y-2">
          <ConditionLeaf
            condition={value}
            characteristics={characteristics}
            onChange={handleLeafChange}
            onDelete={handleLeafDelete}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground"
            onClick={handleAddCondition}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add condition
          </Button>
        </div>
      )}

      {/* Compound group */}
      {value !== null && isCompoundCondition(value) && (
        <ConditionGroup
          condition={value}
          characteristics={characteristics}
          onChange={handleGroupChange}
          onDelete={handleGroupDelete}
        />
      )}

      {/* Clear all button */}
      {value !== null && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
          onClick={handleClear}
        >
          <X className="h-3.5 w-3.5 mr-1" />
          Clear all
        </Button>
      )}
    </div>
  )
}
