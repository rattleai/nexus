import { describe, it, expect, beforeEach } from "vitest"
import { setAccessToken, getAccessToken, getTokenVersion, parseApiError } from "./api-client"
import { HTTPError, type NormalizedOptions } from "ky"

describe("api-client", () => {
  beforeEach(() => {
    setAccessToken(null)
  })

  describe("setAccessToken / getAccessToken", () => {
    it("round-trips a token value", () => {
      setAccessToken("test-token-123")
      expect(getAccessToken()).toBe("test-token-123")
    })

    it("clears the token when set to null", () => {
      setAccessToken("test-token")
      setAccessToken(null)
      expect(getAccessToken()).toBeNull()
    })
  })

  describe("getTokenVersion", () => {
    it("increments on each setAccessToken call", () => {
      const v1 = getTokenVersion()
      setAccessToken("token-a")
      const v2 = getTokenVersion()
      setAccessToken("token-b")
      const v3 = getTokenVersion()

      expect(v2).toBe(v1 + 1)
      expect(v3).toBe(v2 + 1)
    })
  })

  describe("parseApiError", () => {
    it("extracts detail from a structured HTTP error response", async () => {
      const response = new Response(
        JSON.stringify({ detail: "Invalid credentials", code: "AUTH_FAILED" }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      )
      const httpError = new HTTPError(
        response,
        new Request("http://localhost/api/v1/test"),
        {} as NormalizedOptions,
      )

      const result = await parseApiError(httpError)
      expect(result.detail).toBe("Invalid credentials")
      expect(result.code).toBe("AUTH_FAILED")
    })

    it("returns error message for Error instances", async () => {
      const result = await parseApiError(new Error("Network failure"))
      expect(result.detail).toBe("Network failure")
    })

    it("returns fallback for non-Error values", async () => {
      const result = await parseApiError("some string error")
      // Returns i18n.t("unexpected_error") fallback — the value depends on i18n init
      expect(result).toHaveProperty("detail")
    })
  })
})
