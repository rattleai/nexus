import { memo, useCallback } from "react"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { Characteristic } from "@/types/configurator"
import type { CompoundCondition, ConditionNode } from "./condition-types"
import { isCompoundCondition } from "./condition-types"
import { createEmptyLeaf, createEmptyGroup } from "./condition-utils"
import { ConditionLeaf } from "./condition-leaf"

interface ConditionGroupProps {
  condition: CompoundCondition
  characteristics: Characteristic[]
  onChange: (condition: CompoundCondition) => void
  onDelete: () => void
  depth?: number
}

export const ConditionGroup = memo(function ConditionGroup({
  condition,
  characteristics,
  onChange,
  onDelete,
  depth = 0,
}: ConditionGroupProps) {
  const isAnd = condition.op === "and"

  const toggleOp = useCallback(() => {
    onChange({
      ...condition,
      op: isAnd ? "or" : "and",
    })
  }, [condition, isAnd, onChange])

  const addCondition = useCallback(() => {
    onChange({
      ...condition,
      conditions: [...condition.conditions, createEmptyLeaf()],
    })
  }, [condition, onChange])

  const addGroup = useCallback(() => {
    onChange({
      ...condition,
      conditions: [
        ...condition.conditions,
        createEmptyGroup(isAnd ? "or" : "and"),
      ],
    })
  }, [condition, isAnd, onChange])

  const updateChild = useCallback(
    (index: number, updated: ConditionNode) => {
      const next = [...condition.conditions]
      next[index] = updated
      onChange({ ...condition, conditions: next })
    },
    [condition, onChange],
  )

  const deleteChild = useCallback(
    (index: number) => {
      const next = condition.conditions.filter((_, i) => i !== index)
      onChange({ ...condition, conditions: next })
    },
    [condition, onChange],
  )

  return (
    <div
      className={cn(
        "rounded-lg border border-border/50 bg-card/30",
        "border-l-2",
        isAnd ? "border-l-blue-500/60" : "border-l-amber-500/60",
        depth > 0 && "ml-4",
      )}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/30">
        <Badge
          variant="outline"
          className={cn(
            "cursor-pointer select-none transition-colors text-xs font-medium",
            isAnd
              ? "border-blue-500/40 text-blue-400 hover:bg-blue-500/10"
              : "border-amber-500/40 text-amber-400 hover:bg-amber-500/10",
          )}
          onClick={toggleOp}
        >
          {isAnd ? "AND" : "OR"}
        </Badge>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={addCondition}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Condition
        </Button>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={addGroup}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Group
        </Button>

        <div className="flex-1" />

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Children */}
      <div className="flex flex-col gap-2 p-3">
        {condition.conditions.length === 0 && (
          <p className="text-xs text-muted-foreground italic px-1">
            No conditions yet. Add a condition or group.
          </p>
        )}

        {condition.conditions.map((child, index) => {
          if (isCompoundCondition(child)) {
            return (
              <ConditionGroup
                key={index}
                condition={child}
                characteristics={characteristics}
                onChange={(updated) => updateChild(index, updated)}
                onDelete={() => deleteChild(index)}
                depth={depth + 1}
              />
            )
          }

          // Leaf condition (or NotCondition, which we treat as leaf for now)
          return (
            <ConditionLeaf
              key={index}
              condition={child as import("./condition-types").LeafCondition}
              characteristics={characteristics}
              onChange={(updated) => updateChild(index, updated)}
              onDelete={() => deleteChild(index)}
            />
          )
        })}
      </div>
    </div>
  )
})
