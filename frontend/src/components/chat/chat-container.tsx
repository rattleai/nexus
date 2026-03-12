import * as React from "react"
import { cn } from "@/lib/utils"
import { ChatMessage } from "./chat-message"
import { TypingIndicator } from "./typing-indicator"

export interface ChatMessageData {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp?: string
}

interface ChatContainerProps {
  messages: ChatMessageData[]
  isLoading?: boolean
  className?: string
}

export function ChatContainer({
  messages,
  isLoading = false,
  className,
}: ChatContainerProps) {
  const bottomRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, isLoading])

  return (
    <div
      className={cn(
        "flex flex-1 flex-col overflow-y-auto",
        className,
      )}
    >
      {messages.length === 0 && (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          No messages yet. Start a conversation.
        </div>
      )}

      {messages.map((message) => (
        <ChatMessage
          key={message.id}
          role={message.role}
          content={message.content}
          timestamp={message.timestamp}
        />
      ))}

      {isLoading && (
        <div className="flex gap-3 px-4 py-3">
          <TypingIndicator />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
