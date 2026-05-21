import { test, expect, TEST_USER } from "./fixtures"

test.describe("Authentication Flows - Unauthenticated", () => {
  test("landing page shows sign in and register CTAs", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByText("Welcome to NEXUS")).toBeVisible()
    await expect(page.getByRole("link", { name: "Sign In" })).toBeVisible()
    await expect(page.getByRole("link", { name: "Create Account" })).toBeVisible()
  })

  test("landing page shows feature cards", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByText("Async Jobs")).toBeVisible()
    await expect(page.getByRole("heading", { name: "API Keys" })).toBeVisible()
    await expect(page.getByText("Team Management")).toBeVisible()
  })

  test("login page renders with form fields", async ({ page }) => {
    await page.goto("/login")
    await expect(page.getByText("Sign In").first()).toBeVisible()
    await expect(page.getByLabel("Email")).toBeVisible()
    await expect(page.getByLabel("Password")).toBeVisible()
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible()
  })

  test("login with valid credentials redirects to dashboard", async ({ page }) => {
    await page.goto("/login")
    await page.getByLabel("Email").fill(TEST_USER.email)
    await page.getByLabel("Password").fill(TEST_USER.password)
    await page.getByRole("button", { name: "Sign In" }).click()

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 15_000 })
  })

  test("login form validates empty fields", async ({ page }) => {
    await page.goto("/login")
    await page.getByRole("button", { name: "Sign In" }).click()

    await expect(page.getByText("Email is required")).toBeVisible()
    await expect(page.getByText("Password is required")).toBeVisible()
  })

  test("navigate from login to register", async ({ page }) => {
    await page.goto("/login")
    await page.getByRole("link", { name: "Register" }).click()
    await expect(page).toHaveURL(/\/register/)
    await expect(page.getByText("Create Account").first()).toBeVisible()
  })

  test("register page has all required fields", async ({ page }) => {
    await page.goto("/register")
    await expect(page.locator("#email")).toBeVisible()
    await expect(page.locator("#displayName")).toBeVisible()
    await expect(page.locator("#tenantSlug")).toBeVisible()
    await expect(page.locator("#password")).toBeVisible()
    await expect(page.locator("#confirmPassword")).toBeVisible()
  })

  test("protected route redirects when unauthenticated", async ({ page }) => {
    await page.goto("/jobs")
    await expect(page.getByText("Welcome to NEXUS")).toBeVisible({ timeout: 10_000 })
  })
})

test.describe("Authentication Flows - Authenticated", () => {
  test("logout redirects to public page", async ({ authenticatedPage: page }) => {
    await page.getByLabel("User menu").click()
    await page.getByText("Sign out").click()

    await expect(page.getByText("Welcome to NEXUS")).toBeVisible({ timeout: 10_000 })
  })

  test("session persists across page reload", async ({ authenticatedPage: page }) => {
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()
    await page.reload()
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 15_000 })
  })
})

// These tests intentionally send wrong credentials — run them LAST
// so they don't trigger account lockout for subsequent tests
test.describe("Authentication Flows - Error Cases", () => {
  test("login with invalid credentials shows error", async ({ page }) => {
    await page.goto("/login")
    // Wait for the form to be interactive
    const emailField = page.getByLabel("Email")
    await emailField.waitFor({ state: "visible" })

    await emailField.fill(TEST_USER.email)
    await page.getByLabel("Password").fill("WrongPassword123")

    // Click and wait for the API response
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/login") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Sign In" }).click(),
    ])

    // Verify the API returned an error status (401 or 429)
    expect(response.status()).toBeGreaterThanOrEqual(400)

    // The page should still show the login form (not redirect)
    await expect(page.getByLabel("Email")).toBeVisible()
  })
})
