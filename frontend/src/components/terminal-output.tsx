import * as React from "react"
import { useTranslation } from "react-i18next"
import { Check, Copy } from "lucide-react"
import { cn } from "@/lib/utils"
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard"

interface TerminalLine {
  content: string
  type?: "stdout" | "stderr" | "info" | "command"
  timestamp?: string
}

interface TerminalOutputProps {
  lines: TerminalLine[]
  title?: string
  className?: string
  maxHeight?: number
  showLineNumbers?: boolean
}

const lineTypeStyles: Record<NonNullable<TerminalLine["type"]>, string> = {
  stdout: "text-zinc-200",
  stderr: "text-red-400",
  info: "text-blue-400",
  command: "text-green-400",
}

const lineTypePrefix: Record<NonNullable<TerminalLine["type"]>, string> = {
  stdout: "",
  stderr: "",
  info: "ℹ ",
  command: "$ ",
}

export function TerminalOutput({
  lines,
  title,
  className,
  maxHeight = 400,
  showLineNumbers = false,
}: TerminalOutputProps) {
  const { t } = useTranslation()
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const { copied, copy } = useCopyToClipboard()

  // Auto-scroll to bottom when lines change
  React.useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [lines])

  const fullText = React.useMemo(
    () => lines.map((l) => l.content).join("\n"),
    [lines],
  )

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 text-sm shadow-lg",
        className,
      )}
    >
      {/* Title bar */}
      <div className="flex items-center justify-between border-b border-zinc-700 bg-zinc-800 px-4 py-2.5">
        <div className="flex items-center gap-3">
          {/* macOS-style dots */}
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full bg-red-500" />
            <span className="h-3 w-3 rounded-full bg-yellow-500" />
            <span className="h-3 w-3 rounded-full bg-green-500" />
          </div>
          <span className="text-xs font-medium text-zinc-400">{title ?? t("terminal.title")}</span>
        </div>
        <button
          type="button"
          onClick={() => copy(fullText)}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-200"
          aria-label={copied ? t("status.copied") : t("aria.copy_all")}
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5" />
              {t("status.copied")}
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" />
              {t("buttons.copy")}
            </>
          )}
        </button>
      </div>

      {/* Terminal content */}
      <div
        ref={scrollRef}
        className="overflow-auto p-4 font-mono text-sm leading-6"
        style={{ maxHeight }}
      >
        {lines.map((line, idx) => {
          const type = line.type ?? "stdout"
          return (
            <div
              key={idx}
              className={cn("flex", lineTypeStyles[type])}
            >
              {showLineNumbers && (
                <span className="mr-4 inline-block w-8 shrink-0 select-none text-right text-zinc-600">
                  {idx + 1}
                </span>
              )}
              {line.timestamp && (
                <span className="mr-3 shrink-0 select-none text-zinc-600">
                  {line.timestamp}
                </span>
              )}
              <span className="min-w-0 whitespace-pre-wrap break-all">
                {lineTypePrefix[type]}
                {line.content}
              </span>
            </div>
          )
        })}

        {lines.length === 0 && (
          <span className="text-zinc-600">{t("labels.no_output")}</span>
        )}
      </div>
    </div>
  )
}
