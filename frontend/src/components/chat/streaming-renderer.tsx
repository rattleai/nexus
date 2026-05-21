import { cn } from "@/lib/utils"

interface StreamingRendererProps {
  content: string
  isStreaming: boolean
  className?: string
}

export function StreamingRenderer({
  content,
  isStreaming,
  className,
}: StreamingRendererProps) {
  return (
    <div className={cn("whitespace-pre-wrap text-sm", className)}>
      {content}
      {isStreaming && (
        <span
          className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-foreground align-middle"
          aria-hidden="true"
        />
      )}
      {isStreaming && <span className="sr-only">Streaming response</span>}
    </div>
  )
}
