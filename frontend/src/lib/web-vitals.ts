import type { Metric } from "web-vitals"

/**
 * Reports Core Web Vitals metrics to the analytics endpoint.
 * Uses `navigator.sendBeacon` for reliable delivery even during page unload.
 */
function reportMetric(metric: Metric) {
  const body = JSON.stringify({
    name: metric.name,
    value: metric.value,
    rating: metric.rating,
    delta: metric.delta,
    id: metric.id,
    navigationType: metric.navigationType,
  })

  if (navigator.sendBeacon) {
    navigator.sendBeacon(
      "/api/v1/analytics/cwv",
      new Blob([body], { type: "application/json" }),
    )
  }
}

/**
 * Initialize Core Web Vitals monitoring.
 * Call once at app startup. Dynamically imports web-vitals to avoid
 * adding to the critical bundle path.
 */
export async function initWebVitals() {
  try {
    const { onLCP, onFID, onCLS, onTTFB, onINP } = await import("web-vitals")
    onLCP(reportMetric)
    onFID(reportMetric)
    onCLS(reportMetric)
    onTTFB(reportMetric)
    onINP(reportMetric)
  } catch {
    // web-vitals not available — skip silently
  }
}
