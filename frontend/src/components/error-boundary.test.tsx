import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import { ErrorBoundary } from "./error-boundary"

// ErrorBoundary uses i18n.t() directly (not useTranslation hook), so mock i18next
vi.mock("i18next", () => ({
  default: {
    t: (key: string) => {
      const map: Record<string, string> = {
        "boundary.title": "Something went wrong",
        "boundary.description": "An unexpected error occurred.",
        "boundary.reload": "Reload application",
      }
      return map[key] ?? key
    },
    language: "en",
    changeLanguage: vi.fn(),
  },
}))

// Suppress console.error from ErrorBoundary's componentDidCatch
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {})
})

function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("Test error")
  return <div>All good</div>
}

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      <ErrorBoundary>
        <div>Child content</div>
      </ErrorBoundary>,
    )

    expect(screen.getByText("Child content")).toBeInTheDocument()
  })

  it("shows error UI when child throws", () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow />
      </ErrorBoundary>,
    )

    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(screen.getByText("Something went wrong")).toBeInTheDocument()
    expect(screen.getByText("An unexpected error occurred.")).toBeInTheDocument()
    expect(screen.getByText("Reload application")).toBeInTheDocument()
  })

  it("renders custom fallback when provided and error occurs", () => {
    render(
      <ErrorBoundary fallback={<div>Custom fallback UI</div>}>
        <ThrowingComponent shouldThrow />
      </ErrorBoundary>,
    )

    expect(screen.getByText("Custom fallback UI")).toBeInTheDocument()
  })

  it("does not show error UI when child does not throw", () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={false} />
      </ErrorBoundary>,
    )

    expect(screen.getByText("All good")).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})
