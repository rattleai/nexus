"use client"

import * as React from "react"
import { ThumbsUp, ThumbsDown, Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

interface MessageFeedbackProps {
  messageId: string
  onFeedback: (
    messageId: string,
    type: "positive" | "negative",
    comment?: string,
  ) => void
  content?: string
  className?: string
}

export function MessageFeedback({
  messageId,
  onFeedback,
  content,
  className,
}: MessageFeedbackProps) {
  const [feedbackGiven, setFeedbackGiven] = React.useState<
    "positive" | "negative" | null
  >(null)
  const [showDialog, setShowDialog] = React.useState(false)
  const [comment, setComment] = React.useState("")
  const [copied, setCopied] = React.useState(false)

  const handlePositive = () => {
    setFeedbackGiven("positive")
    onFeedback(messageId, "positive")
  }

  const handleNegative = () => {
    setShowDialog(true)
  }

  const handleNegativeSubmit = () => {
    setFeedbackGiven("negative")
    onFeedback(messageId, "negative", comment || undefined)
    setShowDialog(false)
    setComment("")
  }

  const handleCopy = async () => {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API not available
    }
  }

  return (
    <>
      <div className={cn("flex items-center gap-1", className)}>
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            "h-7 w-7",
            feedbackGiven === "positive" && "text-green-500",
          )}
          onClick={handlePositive}
          disabled={feedbackGiven !== null}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
          <span className="sr-only">Helpful</span>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            "h-7 w-7",
            feedbackGiven === "negative" && "text-red-500",
          )}
          onClick={handleNegative}
          disabled={feedbackGiven !== null}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
          <span className="sr-only">Not helpful</span>
        </Button>
        {content && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleCopy}
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-500" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            <span className="sr-only">Copy message</span>
          </Button>
        )}
      </div>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Provide feedback</DialogTitle>
            <DialogDescription>
              What was the issue with this response? Your feedback helps improve
              future responses.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Tell us what went wrong (optional)..."
            rows={4}
          />
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setShowDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleNegativeSubmit}>Submit feedback</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
