import * as React from "react"
import { useTranslation } from "react-i18next"
import { Download, ExternalLink, FileText } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

interface PDFViewerProps {
  src: string
  title?: string
  className?: string
  height?: number | string
}

export function PDFViewer({
  src,
  title,
  className,
  height = 600,
}: PDFViewerProps) {
  const { t } = useTranslation()
  const [hasError, setHasError] = React.useState(false)

  const computedHeight = typeof height === "number" ? `${height}px` : height

  const handleOpenNewTab = React.useCallback(() => {
    window.open(src, "_blank", "noopener,noreferrer")
  }, [src])

  const handleDownload = React.useCallback(() => {
    const link = document.createElement("a")
    link.href = src
    link.download = title ?? "document.pdf"
    link.rel = "noopener noreferrer"
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }, [src, title])

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm",
        className,
      )}
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b bg-muted/50 px-4 py-2.5">
        <div className="flex items-center gap-2 overflow-hidden">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          {title && (
            <span className="truncate text-sm font-medium">{title}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleOpenNewTab}
            aria-label={t("aria.open_new_tab")}
          >
            <ExternalLink className="mr-1.5 h-4 w-4" />
            {t("buttons.open")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDownload}
            aria-label={t("aria.download_pdf")}
          >
            <Download className="mr-1.5 h-4 w-4" />
            {t("buttons.download")}
          </Button>
        </div>
      </div>

      {/* PDF embed */}
      {hasError ? (
        <div
          className="flex flex-col items-center justify-center gap-3 p-8 text-center"
          style={{ height: computedHeight }}
        >
          <FileText className="h-12 w-12 text-muted-foreground/50" />
          <div>
            <p className="text-sm font-medium">{t("pdf_viewer.unable_to_display")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("pdf_viewer.browser_no_support")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleOpenNewTab}>
              <ExternalLink className="mr-1.5 h-4 w-4" />
              {t("pdf_viewer.open_new_tab")}
            </Button>
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="mr-1.5 h-4 w-4" />
              {t("buttons.download")}
            </Button>
          </div>
        </div>
      ) : (
        <object
          data={src}
          type="application/pdf"
          className="w-full"
          style={{ height: computedHeight }}
          aria-label={title ?? "PDF document"}
        >
          {/* Fallback if <object> fails */}
          <iframe
            src={src}
            title={title ?? "PDF document"}
            className="w-full border-0"
            style={{ height: computedHeight }}
            onError={() => setHasError(true)}
          >
            <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
              <p className="text-sm text-muted-foreground">
                {t("pdf_viewer.browser_no_embed")}
              </p>
              <Button variant="outline" size="sm" onClick={handleOpenNewTab}>
                {t("pdf_viewer.open_new_tab")}
              </Button>
            </div>
          </iframe>
        </object>
      )}
    </div>
  )
}
