/**
 * Get the application base URL for billing redirects and other purposes.
 *
 * In development, this is configured via VITE_APP_BASE_URL environment variable.
 * In production, it's typically the same as window.location.origin.
 */
export function getAppBaseUrl(): string {
  // Use environment variable if available (development)
  const envUrl = import.meta.env.VITE_APP_BASE_URL
  if (envUrl) {
    return envUrl
  }

  // Fall back to current origin (production)
  return window.location.origin
}

/**
 * Get the return URL for Stripe redirects.
 * This must match the backend's APP_BASE_URL validation.
 */
export function getBillingReturnUrl(): string {
  return `${getAppBaseUrl()}/billing`
}
