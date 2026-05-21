import { test, expect } from "./fixtures"

test.describe("Responsive Design", () => {
  test("mobile: bottom nav visible when authenticated", async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    // Reload after viewport change to trigger mobile layout
    await page.reload()
    await page.waitForSelector("text=Dashboard", { timeout: 15_000 })

    const bottomNav = page.locator("nav[aria-label='Primary']")
    await expect(bottomNav).toBeVisible()
    await expect(bottomNav.getByText("Dashboard")).toBeVisible()
    await expect(bottomNav.getByText("Agents")).toBeVisible()
  })

  test("mobile: bottom nav hidden when unauthenticated", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto("/")
    // Wait for auth check to complete (loading spinner should disappear)
    await expect(page.getByText("Welcome to NEXUS")).toBeVisible({ timeout: 15_000 })

    const bottomNav = page.locator("nav[aria-label='Primary']")
    await expect(bottomNav).not.toBeVisible()
  })

  test("mobile: login page is responsive", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto("/login")

    await expect(page.getByText("Sign In").first()).toBeVisible()
    await expect(page.getByLabel("Email")).toBeVisible()
    await expect(page.getByLabel("Password")).toBeVisible()
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible()
  })

  test("tablet: dashboard renders correctly", async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width: 810, height: 1080 })
    await page.reload()
    await page.waitForSelector("text=Dashboard", { timeout: 15_000 })

    await expect(page.getByText("Total Jobs")).toBeVisible()
    await expect(page.getByText("Storage")).toBeVisible()
  })

  test("desktop: full layout with sidebar and header", async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.reload()
    await page.waitForSelector("text=Dashboard", { timeout: 15_000 })

    await expect(page.locator("#main-content")).toBeVisible()
    await expect(page.getByLabel("User menu")).toBeVisible()
  })
})
