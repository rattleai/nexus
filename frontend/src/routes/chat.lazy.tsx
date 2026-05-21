import { useCallback, useRef, useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { AuthGuard } from "@/components/auth/auth-guard"
import { PageHeader } from "@/components/page-header"
import { ChatContainer } from "@/components/chat/chat-container"
import { PromptInput } from "@/components/chat/prompt-input"
import { api, parseApiError } from "@/lib/api-client"
import { Card, CardContent } from "@/components/ui/card"

export const Route = createLazyFileRoute("/chat")({
  component: ChatPage,
})

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp?: string
}

function ChatPage() {
  const { t } = useTranslation("chat")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const idCounter = useRef(0)

  const handleSubmit = useCallback(async (content: string) => {
    const userMsg: ChatMessage = {
      id: String(++idCounter.current),
      role: "user",
      content,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    try {
      const res = await api
        .post("chat", { json: { message: content } })
        .json<{ response: string }>()

      const assistantMsg: ChatMessage = {
        id: String(++idCounter.current),
        role: "assistant",
        content: res.response,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
      // Add error as assistant message
      setMessages((prev) => [
        ...prev,
        {
          id: String(++idCounter.current),
          role: "assistant",
          content: t("error_message"),
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }, [t])

  return (
    <AuthGuard>
      <div className="flex flex-col h-[calc(100vh-8rem)]">
        <PageHeader title={t("title")} description={t("description")} />
        <Card className="flex-1 mt-4 flex flex-col overflow-hidden">
          <CardContent className="flex-1 flex flex-col p-4 overflow-hidden">
            <div className="flex-1 overflow-auto">
              <ChatContainer messages={messages} isLoading={isLoading} />
            </div>
            <div className="pt-4 border-t mt-4">
              <PromptInput onSubmit={handleSubmit} disabled={isLoading} />
            </div>
          </CardContent>
        </Card>
      </div>
    </AuthGuard>
  )
}
