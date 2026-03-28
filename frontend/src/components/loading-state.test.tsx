import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { LoadingState } from "./loading-state"

// The i18n mock in test-setup.ts returns the last key segment capitalized.
// So t("labels.loading") → "Loading"

describe("LoadingState", () => {
  it("renders spinner variant by default with aria-busy", () => {
    render(<LoadingState />)

    const container = screen.getByLabelText("Loading")
    expect(container).toHaveAttribute("aria-busy", "true")
  })

  it("renders custom message in spinner variant", () => {
    render(<LoadingState message="Fetching data..." />)

    expect(screen.getByText("Fetching data...")).toBeInTheDocument()
  })

  it("renders skeleton variant with correct number of rows", () => {
    render(<LoadingState variant="skeleton" rows={5} />)

    const container = screen.getByLabelText("Loading")
    expect(container).toHaveAttribute("aria-busy", "true")
    // Each skeleton row is a direct child div
    expect(container.children).toHaveLength(5)
  })

  it("renders skeleton variant with default 3 rows", () => {
    render(<LoadingState variant="skeleton" />)

    const container = screen.getByLabelText("Loading")
    expect(container.children).toHaveLength(3)
  })

  it("renders inline variant with loading text", () => {
    render(<LoadingState variant="inline" />)

    expect(screen.getByText("Loading")).toBeInTheDocument()
  })

  it("renders inline variant with custom message", () => {
    render(<LoadingState variant="inline" message="Please wait..." />)

    expect(screen.getByText("Please wait...")).toBeInTheDocument()
  })
})
