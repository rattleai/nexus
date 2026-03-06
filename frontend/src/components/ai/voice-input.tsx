import { useEffect } from "react"
import { Mic, MicOff, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { useVoiceInput } from "@/hooks/use-voice-input"

interface VoiceInputProps {
  onTranscript: (text: string) => void
  onError?: (error: string) => void
  language?: string
  className?: string
}

export function VoiceInput({
  onTranscript,
  onError,
  language = "en-US",
  className,
}: VoiceInputProps) {
  const {
    isListening,
    transcript,
    interimTranscript,
    startListening,
    stopListening,
    isSupported,
    error,
  } = useVoiceInput({ language })

  const handleToggle = () => {
    if (isListening) {
      stopListening()
      if (transcript) onTranscript(transcript)
    } else {
      startListening()
    }
  }

  useEffect(() => {
    if (error && onError) onError(error)
  }, [error, onError])

  if (!isSupported) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            disabled
            className={cn("h-8 w-8", className)}
          >
            <MicOff className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Voice input not supported in this browser</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant={isListening ? "destructive" : "ghost"}
            size="icon"
            className={cn(
              "relative h-8 w-8",
              isListening && "animate-pulse",
            )}
            onClick={handleToggle}
          >
            {isListening ? (
              <Square className="h-3.5 w-3.5" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
            {isListening && (
              <span className="absolute inset-0 animate-ping rounded-md bg-red-500/20" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          {isListening ? "Stop recording" : "Start voice input"}
        </TooltipContent>
      </Tooltip>
      {isListening && interimTranscript && (
        <span className="max-w-[200px] truncate text-xs text-muted-foreground italic">
          {interimTranscript}
        </span>
      )}
    </div>
  )
}
