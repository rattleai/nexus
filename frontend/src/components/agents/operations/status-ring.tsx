
interface StatusRingProps {
  data: Record<string, number>
  total: number
  size?: number
}

// SVG stroke requires literal color values — Tailwind classes can't be used here.
// Hex values match the Tailwind palette; status semantics are fixed.
const STATUS_COLORS: Record<string, string> = {
  completed: "#10b981", // emerald-500
  failed: "#ef4444",    // red-500
  running: "#3b82f6",   // blue-500
  pending: "#94a3b8",   // slate-400
  cancelled: "#6b7280", // gray-500
  paused: "#f59e0b",    // amber-500
}

export function StatusRing({ data, total, size = 120 }: StatusRingProps) {
  const radius = (size - 16) / 2
  const circumference = 2 * Math.PI * radius
  const center = size / 2

  if (total === 0) {
    return (
      <div className="flex flex-col items-center">
        <svg width={size} height={size} className="block" role="img" aria-label="No runs to display">
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={10}
            className="text-muted/50"
          />
        </svg>
        <p className="text-xs text-muted-foreground mt-2">No runs yet</p>
      </div>
    )
  }

  // Build segments
  const segments: Array<{ key: string; color: string; pct: number }> = []
  for (const [status, count] of Object.entries(data)) {
    if (count <= 0) continue
    segments.push({
      key: status,
      color: STATUS_COLORS[status] ?? "#6b7280",
      pct: count / total,
    })
  }

  // Sort: completed first, then failed, then rest
  const order = ["completed", "running", "pending", "paused", "cancelled", "failed"]
  segments.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))

  let offset = 0

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          className="block -rotate-90"
          role="img"
          aria-label={`Status breakdown: ${segments.map((s) => `${s.key} ${Math.round(s.pct * 100)}%`).join(", ")}`}
        >
          {segments.map((seg) => {
            const dashLength = circumference * seg.pct
            const dashGap = circumference - dashLength
            const el = (
              <circle
                key={seg.key}
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth={10}
                strokeDasharray={`${dashLength} ${dashGap}`}
                strokeDashoffset={-offset}
                strokeLinecap="round"
                className="transition-all duration-500"
              />
            )
            offset += dashLength
            return el
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold tabular-nums">{total}</span>
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
            runs
          </span>
        </div>
      </div>
    </div>
  )
}
