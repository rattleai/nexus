import { useCallback, useRef, useState, type DragEvent } from "react"
import { Upload, X, FileIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/lib/format"

interface FileUploadProps {
  onUpload: (files: File[]) => void | Promise<void>
  accept?: string
  multiple?: boolean
  maxSize?: number
  disabled?: boolean
  className?: string
}

export function FileUpload({
  onUpload,
  accept,
  multiple = false,
  maxSize = 50 * 1024 * 1024,
  disabled = false,
  className,
}: FileUploadProps) {
  const [dragActive, setDragActive] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrag = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true)
    else if (e.type === "dragleave") setDragActive(false)
  }, [])

  const processFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return
      const valid = Array.from(files).filter((f) => f.size <= maxSize)
      setSelectedFiles((prev) => (multiple ? [...prev, ...valid] : valid.slice(0, 1)))
    },
    [maxSize, multiple],
  )

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setDragActive(false)
      processFiles(e.dataTransfer.files)
    },
    [processFiles],
  )

  const handleUpload = async () => {
    if (!selectedFiles.length) return
    setUploading(true)
    try {
      await onUpload(selectedFiles)
      setSelectedFiles([])
    } finally {
      setUploading(false)
    }
  }

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div
        className={cn(
          "border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer",
          dragActive && "border-primary bg-primary/5",
          disabled && "opacity-50 cursor-not-allowed",
          !dragActive && "border-border hover:border-primary/50",
        )}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload files"
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      >
        <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
        <p className="text-sm text-muted-foreground">
          Drag & drop files here, or click to browse
        </p>
        <p className="text-xs text-muted-foreground mt-1">Max {formatBytes(maxSize)} per file</p>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={accept}
          multiple={multiple}
          onChange={(e) => processFiles(e.target.files)}
          disabled={disabled}
        />
      </div>
      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          {selectedFiles.map((file, i) => (
            <div
              key={`${file.name}-${i}`}
              className="flex items-center gap-3 rounded-md border p-3"
            >
              <FileIcon className="h-4 w-4 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation()
                  removeFile(i)
                }}
                aria-label={`Remove ${file.name}`}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button onClick={handleUpload} disabled={uploading} className="w-full">
            {uploading ? "Uploading..." : `Upload ${selectedFiles.length} file(s)`}
          </Button>
        </div>
      )}
    </div>
  )
}
