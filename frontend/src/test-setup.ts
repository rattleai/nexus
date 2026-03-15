import "@testing-library/jest-dom/vitest"
import { vi } from "vitest"

// Mock react-i18next for all tests
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      // Return the last segment of the key as a human-readable fallback
      const parts = key.split(".")
      const lastPart = parts[parts.length - 1]
      // Capitalize first letter and replace underscores with spaces
      let result = lastPart.charAt(0).toUpperCase() + lastPart.slice(1).replace(/_/g, " ")
      // Support basic interpolation (e.g., {{name}})
      if (params && typeof params === "object") {
        Object.entries(params).forEach(([k, v]) => {
          result = result.replace(new RegExp(`\\{\\{${k}\\}\\}`, "g"), String(v ?? ""))
        })
      }
      return result
    },
    i18n: {
      language: "en",
      changeLanguage: vi.fn(),
    },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))
