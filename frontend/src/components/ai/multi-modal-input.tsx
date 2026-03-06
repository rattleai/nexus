import { useCallback } from "react"
import { useDropzone } from "react-dropzone"
import { FileIcon, ImageIcon, Music, Paperclip, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/lib/format"

interface Attachment {
  id: string
  file: File
  type: "image" | "document" | "audio"
  preview?: string
}

interface MultiModalInputProps {
  attachments: Attachment[]
  onAttach: (files: File[]) => void
  onRemove: (id: string) => void
  accept?: string
  maxFiles?: number
  className?: string
}

function getFileType(file: File): Attachment["type"] {
  if (file.type.startsWith("image/")) return "image"
  if (file.type.startsWith("audio/")) return "audio"
  return "document"
}

const typeIcons: Record<Attachment["type"], React.ElementType> = {
  image: ImageIcon,
  document: FileIcon,
  audio: Music,
}

export function MultiModalInput({
  attachments,
  onAttach,
  onRemove,
  accept = "image/*,.pdf,.doc,.docx,.txt,.mp3,.wav",
  maxFiles = 10,
  className,
}: MultiModalInputProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      const remaining = maxFiles - attachments.length
      if (remaining > 0) onAttach(accepted.slice(0, remaining))
    },
    [onAttach, attachments.length, maxFiles],
  )

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: accept
      ? Object.fromEntries(accept.split(",").map((t) => [t.trim(), []]))
      : undefined,
    noClick: true,
    noKeyboard: true,
    maxFiles: maxFiles - attachments.length,
  })

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const files = Array.from(e.clipboardData.files)
      if (files.length) {
        e.preventDefault()
        const remaining = maxFiles - attachments.length
        if (remaining > 0) onAttach(files.slice(0, remaining))
      }
    },
    [onAttach, attachments.length, maxFiles],
  )

  return (
    <div
      {...getRootProps()}
      onPaste={handlePaste}
      className={cn(
        "relative",
        isDragActive && "ring-2 ring-primary ring-offset-2 rounded-lg",
        className,
      )}
    >
      <input {...getInputProps()} />

      {isDragActive && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/5">
          <p className="text-sm font-medium text-primary">Drop files here</p>
        </div>
      )}

      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachments.map((attachment) => {
            const Icon = typeIcons[attachment.type]
            return (
              <div
                key={attachment.id}
                className="group relative flex items-center gap-2 rounded-md border bg-muted/50 px-2 py-1.5"
              >
                {attachment.type === "image" && attachment.preview ? (
                  <img
                    src={attachment.preview}
                    alt=""
                    className="h-8 w-8 rounded object-cover"
                  />
                ) : (
                  <Icon className="h-4 w-4 text-muted-foreground" />
                )}
                <div className="min-w-0">
                  <p className="max-w-[120px] truncate text-xs font-medium">
                    {attachment.file.name}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {formatBytes(attachment.file.size)}
                  </p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onRemove(attachment.id)
                  }}
                  className="ml-1 rounded-full p-0.5 hover:bg-muted"
                  aria-label={`Remove ${attachment.file.name}`}
                >
                  <X className="h-3 w-3 text-muted-foreground" />
                </button>
              </div>
            )
          })}
        </div>
      )}

      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1 text-xs text-muted-foreground"
        onClick={open}
      >
        <Paperclip className="h-3.5 w-3.5" />
        Attach
      </Button>
    </div>
  )
}

export type { Attachment, MultiModalInputProps }
export { getFileType }
