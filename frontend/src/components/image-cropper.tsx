import * as React from "react"
import { Crop, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

interface ImageCropperProps {
  src: string
  aspectRatio?: number
  onCrop: (croppedBlob: Blob) => void
  onCancel: () => void
  className?: string
}

interface CropArea {
  x: number
  y: number
  width: number
  height: number
}

type DragHandle =
  | "move"
  | "nw"
  | "ne"
  | "sw"
  | "se"
  | "n"
  | "s"
  | "e"
  | "w"

export function ImageCropper({
  src,
  aspectRatio,
  onCrop,
  onCancel,
  className,
}: ImageCropperProps) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const imageRef = React.useRef<HTMLImageElement>(null)
  const canvasRef = React.useRef<HTMLCanvasElement>(null)

  const [imageSize, setImageSize] = React.useState({ width: 0, height: 0 })
  const [displaySize, setDisplaySize] = React.useState({ width: 0, height: 0 })
  const [crop, setCrop] = React.useState<CropArea>({ x: 0, y: 0, width: 0, height: 0 })
  const [dragging, setDragging] = React.useState<{
    handle: DragHandle
    startX: number
    startY: number
    startCrop: CropArea
  } | null>(null)
  const [isProcessing, setIsProcessing] = React.useState(false)

  // Initialize crop area when image loads
  const handleImageLoad = React.useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const img = e.currentTarget
      const naturalW = img.naturalWidth
      const naturalH = img.naturalHeight
      setImageSize({ width: naturalW, height: naturalH })

      const container = containerRef.current
      if (!container) return
      const containerRect = container.getBoundingClientRect()
      const maxW = containerRect.width
      const maxH = containerRect.height - 80 // reserve space for buttons

      const scale = Math.min(maxW / naturalW, maxH / naturalH, 1)
      const dispW = naturalW * scale
      const dispH = naturalH * scale
      setDisplaySize({ width: dispW, height: dispH })

      // Default crop: 80% centered, constrained to aspect ratio
      let cropW = dispW * 0.8
      let cropH = dispH * 0.8

      if (aspectRatio) {
        const desiredW = cropH * aspectRatio
        if (desiredW <= cropW) {
          cropW = desiredW
        } else {
          cropH = cropW / aspectRatio
        }
      }

      setCrop({
        x: (dispW - cropW) / 2,
        y: (dispH - cropH) / 2,
        width: cropW,
        height: cropH,
      })
    },
    [aspectRatio],
  )

  const clampCrop = React.useCallback(
    (c: CropArea): CropArea => {
      const minSize = 20
      let { x, y, width, height } = c
      width = Math.max(minSize, Math.min(width, displaySize.width))
      height = Math.max(minSize, Math.min(height, displaySize.height))

      if (aspectRatio) {
        const desiredW = height * aspectRatio
        if (desiredW <= displaySize.width) {
          width = desiredW
        } else {
          width = displaySize.width
          height = width / aspectRatio
        }
      }

      x = Math.max(0, Math.min(x, displaySize.width - width))
      y = Math.max(0, Math.min(y, displaySize.height - height))
      return { x, y, width, height }
    },
    [displaySize, aspectRatio],
  )

  const handlePointerDown = React.useCallback(
    (handle: DragHandle, e: React.PointerEvent) => {
      e.preventDefault()
      e.stopPropagation()
      ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
      setDragging({
        handle,
        startX: e.clientX,
        startY: e.clientY,
        startCrop: { ...crop },
      })
    },
    [crop],
  )

  const handlePointerMove = React.useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return
      e.preventDefault()
      const dx = e.clientX - dragging.startX
      const dy = e.clientY - dragging.startY
      const sc = dragging.startCrop

      let next: CropArea

      if (dragging.handle === "move") {
        next = { ...sc, x: sc.x + dx, y: sc.y + dy }
      } else {
        let newX = sc.x
        let newY = sc.y
        let newW = sc.width
        let newH = sc.height

        const h = dragging.handle
        if (h.includes("w")) {
          newX = sc.x + dx
          newW = sc.width - dx
        }
        if (h.includes("e")) {
          newW = sc.width + dx
        }
        if (h.includes("n")) {
          newY = sc.y + dy
          newH = sc.height - dy
        }
        if (h.includes("s")) {
          newH = sc.height + dy
        }

        if (aspectRatio) {
          if (h === "n" || h === "s") {
            newW = newH * aspectRatio
          } else {
            newH = newW / aspectRatio
          }
          if (h.includes("n")) {
            newY = sc.y + sc.height - newH
          }
          if (h.includes("w")) {
            newX = sc.x + sc.width - newW
          }
        }

        next = { x: newX, y: newY, width: newW, height: newH }
      }

      setCrop(clampCrop(next))
    },
    [dragging, clampCrop, aspectRatio],
  )

  const handlePointerUp = React.useCallback(() => {
    setDragging(null)
  }, [])

  const handleCrop = React.useCallback(async () => {
    const img = imageRef.current
    const canvas = canvasRef.current
    if (!img || !canvas || displaySize.width === 0) return

    setIsProcessing(true)

    try {
      const scaleX = imageSize.width / displaySize.width
      const scaleY = imageSize.height / displaySize.height

      const sourceX = crop.x * scaleX
      const sourceY = crop.y * scaleY
      const sourceW = crop.width * scaleX
      const sourceH = crop.height * scaleY

      canvas.width = Math.round(sourceW)
      canvas.height = Math.round(sourceH)

      const ctx = canvas.getContext("2d")
      if (!ctx) return

      ctx.drawImage(
        img,
        sourceX,
        sourceY,
        sourceW,
        sourceH,
        0,
        0,
        canvas.width,
        canvas.height,
      )

      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/png"),
      )

      if (blob) {
        onCrop(blob)
      }
    } finally {
      setIsProcessing(false)
    }
  }, [crop, imageSize, displaySize, onCrop])

  const handles: DragHandle[] = ["nw", "ne", "sw", "se", "n", "s", "e", "w"]

  const handlePositions: Record<DragHandle, React.CSSProperties> = {
    move: { cursor: "move" },
    nw: { top: -4, left: -4, cursor: "nw-resize" },
    ne: { top: -4, right: -4, cursor: "ne-resize" },
    sw: { bottom: -4, left: -4, cursor: "sw-resize" },
    se: { bottom: -4, right: -4, cursor: "se-resize" },
    n: { top: -4, left: "50%", transform: "translateX(-50%)", cursor: "n-resize" },
    s: { bottom: -4, left: "50%", transform: "translateX(-50%)", cursor: "s-resize" },
    e: { top: "50%", right: -4, transform: "translateY(-50%)", cursor: "e-resize" },
    w: { top: "50%", left: -4, transform: "translateY(-50%)", cursor: "w-resize" },
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-xl border bg-card p-4 text-card-foreground shadow-sm",
        className,
      )}
    >
      {/* Image area */}
      <div
        ref={containerRef}
        className="relative flex items-center justify-center overflow-hidden bg-muted/30"
        style={{ minHeight: 200 }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {displaySize.width > 0 && (
          <div
            className="relative"
            style={{ width: displaySize.width, height: displaySize.height }}
          >
            {/* Dimmed image background */}
            <img
              src={src}
              alt=""
              className="pointer-events-none absolute inset-0 h-full w-full object-contain opacity-40"
              draggable={false}
            />

            {/* Cropped preview area */}
            <div
              className="absolute overflow-hidden border-2 border-white shadow-lg"
              style={{
                left: crop.x,
                top: crop.y,
                width: crop.width,
                height: crop.height,
              }}
            >
              <img
                src={src}
                alt=""
                className="pointer-events-none absolute max-w-none"
                style={{
                  width: displaySize.width,
                  height: displaySize.height,
                  left: -crop.x,
                  top: -crop.y,
                }}
                draggable={false}
              />

              {/* Move handle (entire crop area) */}
              <div
                className="absolute inset-0 cursor-move"
                onPointerDown={(e) => handlePointerDown("move", e)}
              />

              {/* Rule of thirds grid */}
              <div className="pointer-events-none absolute inset-0">
                <div className="absolute left-1/3 top-0 h-full w-px bg-white/30" />
                <div className="absolute left-2/3 top-0 h-full w-px bg-white/30" />
                <div className="absolute left-0 top-1/3 h-px w-full bg-white/30" />
                <div className="absolute left-0 top-2/3 h-px w-full bg-white/30" />
              </div>
            </div>

            {/* Resize handles */}
            {handles.map((handle) => (
              <div
                key={handle}
                className="absolute z-10 h-3 w-3 rounded-full border-2 border-white bg-primary shadow"
                style={{
                  ...handlePositions[handle],
                  position: "absolute",
                  // Position relative to crop area
                  ...(handle.includes("n") && !handlePositions[handle].top?.toString().includes("-")
                    ? {}
                    : {}),
                  // Override position to be relative to crop box
                  left:
                    handle === "nw" || handle === "sw" || handle === "w"
                      ? crop.x - 4
                      : handle === "ne" || handle === "se" || handle === "e"
                        ? crop.x + crop.width - 4
                        : crop.x + crop.width / 2 - 4,
                  top:
                    handle === "nw" || handle === "ne" || handle === "n"
                      ? crop.y - 4
                      : handle === "sw" || handle === "se" || handle === "s"
                        ? crop.y + crop.height - 4
                        : crop.y + crop.height / 2 - 4,
                  cursor: handlePositions[handle].cursor,
                }}
                onPointerDown={(e) => handlePointerDown(handle, e)}
              />
            ))}
          </div>
        )}

        {/* Hidden image for loading and canvas operations */}
        <img
          ref={imageRef}
          src={src}
          alt="Source"
          className={cn(
            "max-h-full max-w-full object-contain",
            displaySize.width > 0 && "hidden",
          )}
          onLoad={handleImageLoad}
          crossOrigin="anonymous"
          draggable={false}
        />
      </div>

      {/* Crop info */}
      {displaySize.width > 0 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {Math.round((crop.width / displaySize.width) * imageSize.width)} &times;{" "}
            {Math.round((crop.height / displaySize.height) * imageSize.height)} px
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onCancel}>
              <X className="mr-1.5 h-4 w-4" />
              Cancel
            </Button>
            <Button size="sm" onClick={handleCrop} disabled={isProcessing}>
              <Crop className="mr-1.5 h-4 w-4" />
              {isProcessing ? "Cropping..." : "Crop"}
            </Button>
          </div>
        </div>
      )}

      {/* Hidden canvas for cropping */}
      <canvas ref={canvasRef} className="hidden" />
    </div>
  )
}
