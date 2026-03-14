import { useMemo } from "react"
import { useTranslation } from "react-i18next"

/**
 * Hook for locale-aware date formatting using Intl.DateTimeFormat.
 */
export function useFormattedDate(
  date: string | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  const { i18n } = useTranslation()
  return useMemo(() => {
    if (!date) return "\u2014"
    try {
      const d = typeof date === "string" ? new Date(date) : date
      return new Intl.DateTimeFormat(i18n.language, {
        dateStyle: "medium",
        ...options,
      }).format(d)
    } catch {
      return String(date)
    }
  }, [date, i18n.language, options])
}

/**
 * Hook for locale-aware number formatting using Intl.NumberFormat.
 */
export function useFormattedNumber(
  num: number | null | undefined,
  options?: Intl.NumberFormatOptions,
): string {
  const { i18n } = useTranslation()
  return useMemo(() => {
    if (num == null) return "\u2014"
    try {
      return new Intl.NumberFormat(i18n.language, options).format(num)
    } catch {
      return String(num)
    }
  }, [num, i18n.language, options])
}

/**
 * Hook for locale-aware currency formatting.
 */
export function useFormattedCurrency(
  amount: number | null | undefined,
  currency = "USD",
): string {
  const { i18n } = useTranslation()
  return useMemo(() => {
    if (amount == null) return "\u2014"
    try {
      return new Intl.NumberFormat(i18n.language, {
        style: "currency",
        currency,
      }).format(amount)
    } catch {
      return String(amount)
    }
  }, [amount, i18n.language, currency])
}
