import type { InstanceStatus } from "@/types/agents"

export const statusBadgeConfig: Record<
  InstanceStatus,
  { variant: "default" | "secondary" | "destructive" | "outline"; className: string }
> = {
  running: { variant: "default", className: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/25" },
  pending: { variant: "outline", className: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border-yellow-500/25" },
  completed: { variant: "secondary", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/25" },
  failed: { variant: "destructive", className: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/25" },
  cancelled: { variant: "outline", className: "text-muted-foreground" },
  paused: { variant: "outline", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/25" },
}

export const statusConfig: Record<
  InstanceStatus,
  { color: string; bg: string; label: string }
> = {
  pending: { color: "text-yellow-600", bg: "bg-yellow-500/15", label: "Pending" },
  running: { color: "text-blue-600", bg: "bg-blue-500/15", label: "Running" },
  paused: { color: "text-amber-600", bg: "bg-amber-500/15", label: "Paused" },
  completed: { color: "text-emerald-600", bg: "bg-emerald-500/15", label: "Completed" },
  failed: { color: "text-red-600", bg: "bg-red-500/15", label: "Failed" },
  cancelled: { color: "text-muted-foreground", bg: "bg-muted", label: "Cancelled" },
}
