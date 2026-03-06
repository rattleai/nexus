"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import { ChevronLeft, ChevronRight, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface ImageLightboxProps {
  images: Array<{ src: string; alt?: string }>
  initialIndex?: number
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImageLightbox({
  images,
  initialIndex = 0,
  open,
  onOpenChange,
}: ImageLightboxProps) {
  const [currentIndex, setCurrentIndex] = React.useState(initialIndex)

  React.useEffect(() => {
    if (open) {
      setCurrentIndex(initialIndex)
    }
  }, [open, initialIndex])

  const goNext = React.useCallback(() => {
    setCurrentIndex((prev) => (prev + 1) % images.length)
  }, [images.length])

  const goPrev = React.useCallback(() => {
    setCurrentIndex((prev) => (prev - 1 + images.length) % images.length)
  }, [images.length])

  const close = React.useCallback(() => {
    onOpenChange(false)
  }, [onOpenChange])

  React.useEffect(() => {
    if (!open) return

    function handleKeyDown(e: KeyboardEvent) {
      switch (e.key) {
        case "Escape":
          close()
          break
        case "ArrowRight":
          goNext()
          break
        case "ArrowLeft":
          goPrev()
          break
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    document.body.style.overflow = "hidden"

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      document.body.style.overflow = ""
    }
  }, [open, close, goNext, goPrev])

  if (!open || images.length === 0) return null

  const current = images[currentIndex]

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="Image lightbox"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/90 backdrop-blur-sm"
        onClick={close}
        aria-hidden="true"
      />

      {/* Close button */}
      <button
        type="button"
        className="absolute right-4 top-4 z-10 rounded-sm p-2 text-white/70 transition-colors hover:text-white focus:outline-none focus:ring-2 focus:ring-white/50"
        onClick={close}
        aria-label="Close lightbox"
      >
        <X className="h-6 w-6" />
      </button>

      {/* Image counter */}
      {images.length > 1 && (
        <div className="absolute top-4 left-1/2 z-10 -translate-x-1/2 rounded-full bg-black/50 px-3 py-1 text-sm text-white/80">
          {currentIndex + 1} / {images.length}
        </div>
      )}

      {/* Previous button */}
      {images.length > 1 && (
        <button
          type="button"
          className="absolute left-4 z-10 rounded-full bg-black/50 p-2 text-white/70 transition-colors hover:text-white focus:outline-none focus:ring-2 focus:ring-white/50"
          onClick={goPrev}
          aria-label="Previous image"
        >
          <ChevronLeft className="h-6 w-6" />
        </button>
      )}

      {/* Image */}
      <img
        src={current.src}
        alt={current.alt ?? ""}
        className={cn(
          "relative z-[1] max-h-[90vh] max-w-[90vw] select-none object-contain",
        )}
      />

      {/* Next button */}
      {images.length > 1 && (
        <button
          type="button"
          className="absolute right-4 z-10 rounded-full bg-black/50 p-2 text-white/70 transition-colors hover:text-white focus:outline-none focus:ring-2 focus:ring-white/50"
          onClick={goNext}
          aria-label="Next image"
        >
          <ChevronRight className="h-6 w-6" />
        </button>
      )}
    </div>,
    document.body,
  )
}
