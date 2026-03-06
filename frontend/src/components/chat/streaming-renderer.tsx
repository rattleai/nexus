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
          className="ml-0.5 inline-block h-4 w-2 animate-[blink_1s_steps(2)_infinite] bg-foreground align-middle"
          aria-hidden="true"
          style={{
            animationName: "blink",
          }}
        />
      )}
      {isStreaming && <span className="sr-only">Streaming response</span>}
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  )
}
