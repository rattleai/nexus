import * as React from "react"
import { cn } from "@/lib/utils"

interface DiffLine {
  type: "added" | "removed" | "unchanged"
  content: string
  oldLineNumber: number | null
  newLineNumber: number | null
}

interface DiffViewerProps {
  oldValue: string
  newValue: string
  oldTitle?: string
  newTitle?: string
  language?: string
  mode?: "split" | "unified"
  className?: string
}

function computeDiff(oldValue: string, newValue: string): DiffLine[] {
  const oldLines = oldValue.split("\n")
  const newLines = newValue.split("\n")

  // Simple LCS-based diff
  const m = oldLines.length
  const n = newLines.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // Backtrack to build diff
  const result: DiffLine[] = []
  let i = m
  let j = n

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.unshift({
        type: "unchanged",
        content: oldLines[i - 1],
        oldLineNumber: i,
        newLineNumber: j,
      })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({
        type: "added",
        content: newLines[j - 1],
        oldLineNumber: null,
        newLineNumber: j,
      })
      j--
    } else if (i > 0) {
      result.unshift({
        type: "removed",
        content: oldLines[i - 1],
        oldLineNumber: i,
        newLineNumber: null,
      })
      i--
    }
  }

  return result
}

function LineContent({ line }: { line: DiffLine }) {
  return (
    <span className="whitespace-pre-wrap break-all">{line.content || "\u00A0"}</span>
  )
}

function UnifiedView({ lines }: { lines: DiffLine[] }) {
  return (
    <table className="w-full border-collapse font-mono text-sm">
      <tbody>
        {lines.map((line, idx) => (
          <tr
            key={idx}
            className={cn(
              "leading-6",
              line.type === "added" && "bg-green-500/10",
              line.type === "removed" && "bg-red-500/10",
            )}
          >
            <td className="w-12 select-none px-2 text-right text-xs text-muted-foreground">
              {line.oldLineNumber ?? ""}
            </td>
            <td className="w-12 select-none px-2 text-right text-xs text-muted-foreground">
              {line.newLineNumber ?? ""}
            </td>
            <td className="w-6 select-none text-center text-xs">
              {line.type === "added" && (
                <span className="font-semibold text-green-600 dark:text-green-400">+</span>
              )}
              {line.type === "removed" && (
                <span className="font-semibold text-red-600 dark:text-red-400">-</span>
              )}
            </td>
            <td className="px-3">
              <LineContent line={line} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SplitView({ lines }: { lines: DiffLine[] }) {
  // Build paired left/right rows
  const rows: { left: DiffLine | null; right: DiffLine | null }[] = []

  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (line.type === "unchanged") {
      rows.push({ left: line, right: line })
      i++
    } else if (line.type === "removed") {
      // Pair removed lines with subsequent added lines when possible
      const removedStart = i
      while (i < lines.length && lines[i].type === "removed") i++
      const addedStart = i
      while (i < lines.length && lines[i].type === "added") i++

      const removedCount = addedStart - removedStart
      const addedCount = i - addedStart
      const maxCount = Math.max(removedCount, addedCount)

      for (let k = 0; k < maxCount; k++) {
        rows.push({
          left: k < removedCount ? lines[removedStart + k] : null,
          right: k < addedCount ? lines[addedStart + k] : null,
        })
      }
    } else if (line.type === "added") {
      rows.push({ left: null, right: line })
      i++
    } else {
      i++
    }
  }

  return (
    <table className="w-full border-collapse font-mono text-sm">
      <tbody>
        {rows.map((row, idx) => (
          <tr key={idx} className="leading-6">
            {/* Left side */}
            <td
              className={cn(
                "w-12 select-none border-r border-border px-2 text-right text-xs text-muted-foreground",
                row.left?.type === "removed" && "bg-red-500/10",
              )}
            >
              {row.left?.oldLineNumber ?? ""}
            </td>
            <td
              className={cn(
                "w-[50%] border-r border-border px-3",
                row.left?.type === "removed" && "bg-red-500/10",
                !row.left && "bg-muted/30",
              )}
            >
              {row.left ? <LineContent line={row.left} /> : null}
            </td>
            {/* Right side */}
            <td
              className={cn(
                "w-12 select-none border-r border-border px-2 text-right text-xs text-muted-foreground",
                row.right?.type === "added" && "bg-green-500/10",
              )}
            >
              {row.right?.newLineNumber ?? ""}
            </td>
            <td
              className={cn(
                "w-[50%] px-3",
                row.right?.type === "added" && "bg-green-500/10",
                !row.right && "bg-muted/30",
              )}
            >
              {row.right ? <LineContent line={row.right} /> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function DiffViewer({
  oldValue,
  newValue,
  oldTitle = "Original",
  newTitle = "Modified",
  mode = "split",
  className,
}: DiffViewerProps) {
  const lines = React.useMemo(() => computeDiff(oldValue, newValue), [oldValue, newValue])

  return (
    <div className={cn("overflow-hidden rounded-xl border bg-card text-card-foreground", className)}>
      {/* Header */}
      {mode === "split" ? (
        <div className="grid grid-cols-2 border-b bg-muted/50">
          <div className="border-r border-border px-4 py-2 text-sm font-medium text-muted-foreground">
            {oldTitle}
          </div>
          <div className="px-4 py-2 text-sm font-medium text-muted-foreground">
            {newTitle}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-4 border-b bg-muted/50 px-4 py-2">
          <span className="text-sm font-medium text-muted-foreground">{oldTitle}</span>
          <span className="text-xs text-muted-foreground">&rarr;</span>
          <span className="text-sm font-medium text-muted-foreground">{newTitle}</span>
        </div>
      )}

      {/* Diff content */}
      <div className="overflow-x-auto">
        {mode === "split" ? (
          <SplitView lines={lines} />
        ) : (
          <UnifiedView lines={lines} />
        )}
      </div>

      {/* Summary */}
      <div className="flex items-center gap-4 border-t bg-muted/50 px-4 py-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-green-500/60" />
          {lines.filter((l) => l.type === "added").length} added
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-500/60" />
          {lines.filter((l) => l.type === "removed").length} removed
        </span>
      </div>
    </div>
  )
}
