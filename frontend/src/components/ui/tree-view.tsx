import * as React from "react"
import { ChevronRight, File } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

export interface TreeNode {
  id: string
  label: string
  icon?: LucideIcon
  children?: TreeNode[]
}

interface TreeViewProps {
  data: TreeNode[]
  onSelect?: (node: TreeNode) => void
  defaultExpanded?: string[]
  className?: string
}

export function TreeView({
  data,
  onSelect,
  defaultExpanded = [],
  className,
}: TreeViewProps) {
  const [expanded, setExpanded] = React.useState<Set<string>>(
    () => new Set(defaultExpanded),
  )
  const [selected, setSelected] = React.useState<string | null>(null)

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleSelect = (node: TreeNode) => {
    setSelected(node.id)
    onSelect?.(node)
  }

  return (
    <div className={cn("text-sm", className)} role="tree">
      {data.map((node) => (
        <TreeNodeItem
          key={node.id}
          node={node}
          level={0}
          expanded={expanded}
          selected={selected}
          onToggle={toggleExpand}
          onSelect={handleSelect}
        />
      ))}
    </div>
  )
}

interface TreeNodeItemProps {
  node: TreeNode
  level: number
  expanded: Set<string>
  selected: string | null
  onToggle: (id: string) => void
  onSelect: (node: TreeNode) => void
}

function TreeNodeItem({
  node,
  level,
  expanded,
  selected,
  onToggle,
  onSelect,
}: TreeNodeItemProps) {
  const hasChildren = node.children && node.children.length > 0
  const isExpanded = expanded.has(node.id)
  const isSelected = selected === node.id
  const Icon = node.icon ?? (hasChildren ? undefined : File)

  return (
    <div role="treeitem" aria-expanded={hasChildren ? isExpanded : undefined}>
      <button
        type="button"
        className={cn(
          "flex w-full items-center gap-1 rounded-sm px-2 py-1 text-left hover:bg-accent hover:text-accent-foreground",
          isSelected && "bg-accent text-accent-foreground",
        )}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={() => {
          if (hasChildren) {
            onToggle(node.id)
          }
          onSelect(node)
        }}
        aria-selected={isSelected}
      >
        {hasChildren ? (
          <ChevronRight
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              isExpanded && "rotate-90",
            )}
            aria-hidden="true"
          />
        ) : (
          <span className="h-4 w-4 shrink-0" aria-hidden="true" />
        )}
        {Icon && (
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
        <span className="truncate">{node.label}</span>
      </button>

      {hasChildren && isExpanded && (
        <div role="group">
          {node.children!.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child}
              level={level + 1}
              expanded={expanded}
              selected={selected}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}
