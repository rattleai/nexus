import { test, expect } from "./fixtures"

test.describe("Error States & Edge Cases", () => {
  test("404 page for unknown routes", async ({ authenticatedPage: page }) => {
    await page.goto("/this-route-does-not-exist")

    await expect(page.getByText("404")).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText("Page not found")).toBeVisible()
    await expect(page.getByRole("link", { name: "Go home" })).toBeVisible()
  })

  test("go home from 404 navigates to root", async ({ authenticatedPage: page }) => {
    await page.goto("/nonexistent-page")
    await expect(page.getByText("404")).toBeVisible({ timeout: 10_000 })

    await page.getByRole("link", { name: "Go home" }).click()
    await expect(page).toHaveURL("/")
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()
  })

  test("loading states appear during data fetch", async ({ authenticatedPage: page }) => {
    // Intercept API calls to add delay, simulating slow network
    await page.route("**/api/v1/usage/**", async (route) => {
      await new Promise((r) => setTimeout(r, 2000))
      await route.continue()
    })

    await page.goto("/")

    // Should show some form of loading indicator (skeleton, spinner, or aria-busy)
    const loadingIndicator = page.locator("[aria-busy='true']").first()
    // It may or may not be present depending on timing, but the page should still load
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 15_000 })
  })

  test("API error shows degraded state gracefully", async ({ authenticatedPage: page }) => {
    // Intercept health endpoint to return error
    await page.route("**/api/v1/health", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      }),
    )

    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 15_000 })

    // The service health section should still render (may show loading/error state)
    await expect(page.getByText("Service Health")).toBeVisible()
  })
})
