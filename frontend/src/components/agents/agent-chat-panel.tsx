import * as React from "react"
import { ArrowUp, Square, Trash2, Bot, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { AgentStatus, type AgentState } from "@/components/ai/agent-status"
import { ToolCallDisplay } from "@/components/ai/tool-call-display"
import { useAgentStream, type AgentStreamMessage } from "@/hooks/use-agent-stream"
import { cn } from "@/lib/utils"
import type { AgentDefinition } from "@/types/agents"

interface AgentChatPanelProps {
  agent: AgentDefinition
}

export function AgentChatPanel({ agent }: AgentChatPanelProps) {
  const [inputValue, setInputValue] = React.useState("")
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

  const {
    messages,
    sendMessage,
    isStreaming,
    agentState,
    stop,
    clearMessages,
  } = useAgentStream({
    agentId: agent.id,
  })

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, isStreaming])

  const adjustHeight = React.useCallback(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = "auto"
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
  }, [])

  React.useEffect(() => {
    adjustHeight()
  }, [inputValue, adjustHeight])

  const handleSubmit = () => {
    const trimmed = inputValue.trim()
    if (!trimmed || isStreaming) return
    sendMessage(trimmed)
    setInputValue("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const isDisabled = agent.status !== "active"

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-1 pb-4">
        <div className="flex items-center gap-3">
          <AgentStatus state={agentState as AgentState} />
          {messages.length > 0 && (
            <span className="text-xs text-muted-foreground">
              {messages.filter((m) => m.role === "assistant").length} responses
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (isStreaming) stop()
                clearMessages()
              }}
              className="h-7 text-xs"
            >
              <Trash2 className="mr-1 h-3 w-3" />
              Clear
            </Button>
          )}
        </div>
      </div>

      {isDisabled && (
        <div className="rounded-lg border border-dashed border-yellow-500/50 bg-yellow-500/5 p-4 mb-4 text-center">
          <p className="text-sm text-yellow-600 dark:text-yellow-400">
            This agent is not active. Set its status to <strong>Active</strong> in
            the Config tab to start chatting.
          </p>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-1 pr-1 min-h-0">
        {messages.length === 0 && !isDisabled && (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary mb-4">
              <Bot className="h-8 w-8" />
            </div>
            <h3 className="text-lg font-semibold">{agent.name}</h3>
            <p className="text-sm text-muted-foreground mt-1 max-w-sm">
              {agent.description || "Send a message to start a conversation with this agent."}
            </p>
            {agent.system_prompt && (
              <div className="mt-4 max-w-md">
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  System prompt configured
                </Badge>
              </div>
            )}
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} agentName={agent.name} />
        ))}

        {isStreaming && messages[messages.length - 1]?.role === "assistant" && !messages[messages.length - 1]?.content && (
          <div className="flex gap-3 px-4 py-3">
            <div className="flex gap-1">
              <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="pt-4 border-t mt-2">
        <div className="flex items-end gap-2 rounded-xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isDisabled
                ? "Agent is not active..."
                : `Message ${agent.name}...`
            }
            disabled={isDisabled || isStreaming}
            rows={1}
            className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          {isStreaming ? (
            <Button
              size="icon"
              variant="destructive"
              onClick={stop}
              aria-label="Stop streaming"
              className="h-8 w-8 shrink-0"
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={handleSubmit}
              disabled={isDisabled || !inputValue.trim()}
              aria-label="Send message"
              className="h-8 w-8 shrink-0"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="flex items-center justify-between mt-1.5 px-1">
          <span className="text-[11px] text-muted-foreground">
            Shift+Enter for new line
          </span>
          <span className="text-[11px] text-muted-foreground">
            {agent.model}
          </span>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({
  message,
  agentName,
}: {
  message: AgentStreamMessage
  agentName: string
}) {
  const isUser = message.role === "user"

  return (
    <div className={cn("flex gap-3 py-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "flex-1 min-w-0 space-y-2",
          isUser && "flex flex-col items-end",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">
            {isUser ? "You" : agentName}
          </span>
          {message.tokens && (
            <span className="text-[10px] text-muted-foreground">
              {message.tokens.toLocaleString()} tokens
            </span>
          )}
          {message.cost != null && message.cost > 0 && (
            <span className="text-[10px] text-muted-foreground">
              ${message.cost.toFixed(4)}
            </span>
          )}
        </div>
        <div
          className={cn(
            "rounded-xl px-4 py-2.5 text-sm max-w-[85%] whitespace-pre-wrap",
            isUser
              ? "bg-primary text-primary-foreground"
              : "bg-muted",
          )}
        >
          {message.content || (
            <span className="text-muted-foreground italic">Thinking...</span>
          )}
        </div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-1.5 max-w-[85%]">
            {message.toolCalls.map((tc) => (
              <ToolCallDisplay
                key={tc.id}
                toolCall={{
                  id: tc.id,
                  name: tc.name,
                  arguments: tc.arguments,
                  status: tc.status,
                  result: tc.result,
                  error: tc.error,
                  duration: tc.duration,
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
