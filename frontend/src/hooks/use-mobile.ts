import { useMediaQuery } from "./use-media-query"

const MOBILE_BREAKPOINT = "(max-width: 767px)"

/**
 * Returns true when the viewport is narrower than 768px (mobile).
 * Shared across bottom nav, responsive data views, toast positioning, etc.
 */
export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_BREAKPOINT)
}
