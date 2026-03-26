/**
 * Application-agnostic formatting utilities.
 */

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
})

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
})

const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

const DIVISIONS: Array<{ amount: number; name: Intl.RelativeTimeFormatUnit }> = [
  { amount: 60, name: "seconds" },
  { amount: 60, name: "minutes" },
  { amount: 24, name: "hours" },
  { amount: 7, name: "days" },
  { amount: 4.34524, name: "weeks" },
  { amount: 12, name: "months" },
  { amount: Number.POSITIVE_INFINITY, name: "years" },
]

export function formatDate(date: string | Date): string {
  return dateFormatter.format(new Date(date))
}

export function formatDateTime(date: string | Date): string {
  return dateTimeFormatter.format(new Date(date))
}

export function formatRelativeTime(date: string | Date): string {
  let duration = (new Date(date).getTime() - Date.now()) / 1000

  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return relativeFormatter.format(Math.round(duration), division.name)
    }
    duration /= division.amount
  }

  return formatDate(date)
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat("en-US", options).format(value)
}

export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatCurrency(
  value: number,
  currency = "USD",
  locale = "en-US",
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
  }).format(value)
}

export function formatPercent(value: number, precision = 0): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(value)
}

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const

export function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) return "--"
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${seconds % 60}s`
}

export function formatBytes(bytes: number, precision = 1): string {
  if (bytes === 0) return "0 B"
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    BYTE_UNITS.length - 1,
  )
  const value = bytes / 1024 ** exponent
  return `${value.toFixed(precision)} ${BYTE_UNITS[exponent]}`
}
