import { useState } from "react"
import { useDropzone } from "react-dropzone"
import {
  Upload,
  FileText,
  Trash2,
  ChevronDown,
  ChevronRight,
  Loader2,
  CheckCircle,
  AlertCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/lib/format"

interface DocumentChunk {
  id: string
  content: string
  metadata?: Record<string, string>
  relevanceScore?: number
}

interface RAGDocument {
  id: string
  name: string
  type: string
  size: number
  status: "uploading" | "processing" | "indexed" | "error"
  chunks?: DocumentChunk[]
  progress?: number
}

interface RAGDocumentPanelProps {
  documents: RAGDocument[]
  onUpload: (files: File[]) => void
  onDelete?: (id: string) => void
  className?: string
}

const statusConfig: Record<
  RAGDocument["status"],
  { icon: React.ElementType; color: string; label: string }
> = {
  uploading: { icon: Loader2, color: "text-blue-500", label: "Uploading" },
  processing: { icon: Loader2, color: "text-yellow-500", label: "Processing" },
  indexed: { icon: CheckCircle, color: "text-green-500", label: "Indexed" },
  error: { icon: AlertCircle, color: "text-red-500", label: "Error" },
}

function DocumentItem({
  doc,
  onDelete,
}: {
  doc: RAGDocument
  onDelete?: (id: string) => void
}) {
  const [chunksOpen, setChunksOpen] = useState(false)
  const config = statusConfig[doc.status]
  const StatusIcon = config.icon
  const isLoading = doc.status === "uploading" || doc.status === "processing"

  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-3 p-3">
        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{doc.name}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(doc.size)} · {doc.type}
          </p>
        </div>
        <Badge variant="outline" className="gap-1 text-xs">
          <StatusIcon
            className={cn(
              "h-3 w-3",
              config.color,
              isLoading && "animate-spin",
            )}
          />
          {config.label}
        </Badge>
        {onDelete && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => onDelete(doc.id)}
            aria-label={`Delete ${doc.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      {doc.progress != null && isLoading && (
        <div className="px-3 pb-2">
          <Progress value={doc.progress} className="h-1" />
        </div>
      )}

      {doc.chunks && doc.chunks.length > 0 && (
        <div className="border-t">
          <button
            className="flex w-full items-center gap-1 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setChunksOpen(!chunksOpen)}
          >
            {chunksOpen ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            {doc.chunks.length} chunks
          </button>
          {chunksOpen && (
            <div className="space-y-1 px-3 pb-2">
              {doc.chunks.map((chunk, i) => (
                <div
                  key={chunk.id}
                  className="rounded bg-muted/50 p-2 text-xs"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium">Chunk {i + 1}</span>
                    {chunk.relevanceScore != null && (
                      <Badge variant="secondary" className="text-[10px] px-1">
                        {Math.round(chunk.relevanceScore * 100)}%
                      </Badge>
                    )}
                  </div>
                  <p className="line-clamp-3 text-muted-foreground">
                    {chunk.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function RAGDocumentPanel({
  documents,
  onUpload,
  onDelete,
  className,
}: RAGDocumentPanelProps) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: onUpload,
    accept: {
      "application/pdf": [".pdf"],
      "text/plain": [".txt"],
      "application/msword": [".doc"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/markdown": [".md"],
    },
  })

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div
        {...getRootProps()}
        className={cn(
          "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50",
        )}
      >
        <input {...getInputProps()} />
        <Upload className="h-6 w-6 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">Upload documents</p>
          <p className="text-xs text-muted-foreground">
            PDF, TXT, DOC, DOCX, MD
          </p>
        </div>
      </div>

      {documents.length > 0 && (
        <ScrollArea className="max-h-[500px]">
          <div className="space-y-2">
            {documents.map((doc) => (
              <DocumentItem key={doc.id} doc={doc} onDelete={onDelete} />
            ))}
          </div>
        </ScrollArea>
      )}

      {documents.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No documents uploaded yet
        </p>
      )}
    </div>
  )
}
