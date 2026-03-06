import { cn } from "@/lib/utils"

interface TypingIndicatorProps {
  className?: string
}

export function TypingIndicator({ className }: TypingIndicatorProps) {
  return (
    <div className={cn("flex items-center gap-1 px-2 py-1", className)}>
      <span
        className="inline-block h-2 w-2 rounded-full bg-muted-foreground/40 animate-[bounce_1.4s_infinite_0ms]"
        aria-hidden="true"
      />
      <span
        className="inline-block h-2 w-2 rounded-full bg-muted-foreground/40 animate-[bounce_1.4s_infinite_200ms]"
        aria-hidden="true"
      />
      <span
        className="inline-block h-2 w-2 rounded-full bg-muted-foreground/40 animate-[bounce_1.4s_infinite_400ms]"
        aria-hidden="true"
      />
      <span className="sr-only">Assistant is typing</span>
    </div>
  )
}
