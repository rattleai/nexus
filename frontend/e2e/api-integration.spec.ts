import { test, expect, TEST_USER } from "./fixtures"

test.describe("API Integration", () => {
  test("health live endpoint returns ok", async ({ request }) => {
    const response = await request.get("/api/v1/health/live")
    expect(response.ok()).toBeTruthy()
    const body = await response.json()
    expect(body.status).toBe("ok")
  })

  test("health ready endpoint returns ok", async ({ request }) => {
    const response = await request.get("/api/v1/health/ready")
    expect(response.ok()).toBeTruthy()
    const body = await response.json()
    expect(body.status).toBeDefined()
  })

  test("health aggregate endpoint returns ok", async ({ request }) => {
    const response = await request.get("/api/v1/health")
    expect(response.ok()).toBeTruthy()
    const body = await response.json()
    expect(body.status).toBe("ok")
  })

  test("login API returns expected response shape", async ({ request }) => {
    const response = await request.post("/api/v1/auth/login", {
      data: { email: TEST_USER.email, password: TEST_USER.password },
    })
    expect(response.ok()).toBeTruthy()
    const body = await response.json()

    expect(body.access_token).toBeTruthy()
    expect(body.token_type).toBe("bearer")
    expect(body.expires_in).toBeGreaterThan(0)
    expect(body.user).toBeDefined()
    expect(body.user.email).toBe(TEST_USER.email)
    expect(body.user.role).toBe("owner")
    expect(body.user.email_verified).toBe(true)
  })

  test("authenticated GET /auth/me returns user profile", async ({ request }) => {
    const loginResponse = await request.post("/api/v1/auth/login", {
      data: { email: TEST_USER.email, password: TEST_USER.password },
    })
    const { access_token } = await loginResponse.json()

    const meResponse = await request.get("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(meResponse.ok()).toBeTruthy()
    const user = await meResponse.json()
    expect(user.email).toBe(TEST_USER.email)
    expect(user.display_name).toBe(TEST_USER.displayName)
  })

  test("unauthenticated API call returns 401", async ({ request }) => {
    const response = await request.get("/api/v1/auth/me")
    expect(response.status()).toBe(401)
  })

  test("frontend proxy routes API calls correctly", async ({ authenticatedPage: page }) => {
    const result = await page.evaluate(async () => {
      const res = await fetch("/api/v1/health/live")
      return res.json()
    })
    expect(result.status).toBe("ok")
  })
})

// Invalid login tests at the end to avoid triggering lockout
test.describe("API Integration - Error Cases", () => {
  test("invalid login returns 401", async ({ request }) => {
    const response = await request.post("/api/v1/auth/login", {
      data: { email: TEST_USER.email, password: "WrongPassword" },
    })
    expect(response.status()).toBe(401)
  })
})
