import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AgentToolCallCard } from "./agent-tool-call-card"
import type { AgentToolCall } from "@/stores/agent-conversation-store"

const XSS_PAYLOAD = '<script>alert("xss")</script>'
const IMG_PAYLOAD = '<img src=x onerror=alert("xss")>'

function makeToolCall(overrides: Partial<AgentToolCall> = {}): AgentToolCall {
  return {
    id: "test-tool-call-1",
    toolName: "test_tool",
    args: {},
    status: "completed",
    ...overrides,
  }
}

describe("AgentToolCallCard XSS safety", () => {
  it("escapes script tags in tool results", async () => {
    const user = userEvent.setup()
    const toolCall = makeToolCall({ result: XSS_PAYLOAD })
    render(<AgentToolCallCard toolCall={toolCall} />)

    // Expand the card to reveal result
    await user.click(screen.getByRole("button"))

    // The literal text should appear, not an actual script element
    expect(screen.getByText(XSS_PAYLOAD)).toBeInTheDocument()
    expect(document.querySelector("script")).toBeNull()
  })

  it("escapes img onerror payloads in tool results", async () => {
    const user = userEvent.setup()
    const toolCall = makeToolCall({ result: IMG_PAYLOAD })
    render(<AgentToolCallCard toolCall={toolCall} />)

    await user.click(screen.getByRole("button"))

    expect(screen.getByText(IMG_PAYLOAD)).toBeInTheDocument()
    expect(document.querySelector("img")).toBeNull()
  })

  it("escapes script tags in tool errors", async () => {
    const user = userEvent.setup()
    const toolCall = makeToolCall({
      status: "error",
      error: XSS_PAYLOAD,
    })
    render(<AgentToolCallCard toolCall={toolCall} />)

    await user.click(screen.getByRole("button"))

    expect(screen.getByText(XSS_PAYLOAD)).toBeInTheDocument()
    expect(document.querySelector("script")).toBeNull()
  })

  it("escapes img onerror payloads in tool errors", async () => {
    const user = userEvent.setup()
    const toolCall = makeToolCall({
      status: "error",
      error: IMG_PAYLOAD,
    })
    render(<AgentToolCallCard toolCall={toolCall} />)

    await user.click(screen.getByRole("button"))

    expect(screen.getByText(IMG_PAYLOAD)).toBeInTheDocument()
    expect(document.querySelector("img")).toBeNull()
  })

  it("escapes XSS payloads in tool arguments", async () => {
    const user = userEvent.setup()
    const toolCall = makeToolCall({
      args: { query: XSS_PAYLOAD, path: IMG_PAYLOAD },
    })
    render(<AgentToolCallCard toolCall={toolCall} />)

    await user.click(screen.getByRole("button"))

    // Arguments are rendered via JSON.stringify, so the payload appears
    // as a JSON string value. Verify the raw text is present and no
    // script/img elements were injected.
    expect(screen.getByText(/"query"/)).toBeInTheDocument()
    expect(document.querySelector("script")).toBeNull()
    expect(document.querySelector("img")).toBeNull()
  })

  it("escapes XSS payloads in tool name", async () => {
    const toolCall = makeToolCall({
      toolName: XSS_PAYLOAD,
    })
    render(<AgentToolCallCard toolCall={toolCall} />)

    // Tool name is visible without expanding
    expect(screen.getByText(XSS_PAYLOAD)).toBeInTheDocument()
    expect(document.querySelector("script")).toBeNull()
  })
})
