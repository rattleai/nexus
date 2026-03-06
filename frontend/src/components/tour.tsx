"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export interface TourStep {
  target: string
  title: string
  description: string
  placement?: "top" | "bottom" | "left" | "right"
}

interface TourProps {
  steps: TourStep[]
  active: boolean
  onComplete: () => void
  onSkip?: () => void
}

interface TargetRect {
  top: number
  left: number
  width: number
  height: number
}

export function Tour({ steps, active, onComplete, onSkip }: TourProps) {
  const [currentStep, setCurrentStep] = React.useState(0)
  const [targetRect, setTargetRect] = React.useState<TargetRect | null>(null)

  const clampedStep = Math.min(currentStep, steps.length - 1)
  const step = steps[clampedStep]

  const updateTargetRect = React.useCallback(() => {
    if (!step) return
    const el = document.querySelector(step.target)
    if (!el) {
      setTargetRect(null)
      return
    }
    const rect = el.getBoundingClientRect()
    setTargetRect({
      top: rect.top + window.scrollY,
      left: rect.left + window.scrollX,
      width: rect.width,
      height: rect.height,
    })
  }, [step])

  React.useEffect(() => {
    if (!active) {
      setCurrentStep(0)
      return
    }
    updateTargetRect()

    window.addEventListener("resize", updateTargetRect)
    window.addEventListener("scroll", updateTargetRect, true)
    return () => {
      window.removeEventListener("resize", updateTargetRect)
      window.removeEventListener("scroll", updateTargetRect, true)
    }
  }, [active, currentStep, updateTargetRect])

  React.useEffect(() => {
    if (!active) return

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onSkip?.()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [active, onSkip])

  if (!active || !step) return null

  const isFirst = currentStep === 0
  const isLast = currentStep === steps.length - 1

  function handleNext() {
    if (isLast) {
      onComplete()
    } else {
      setCurrentStep((prev) => prev + 1)
    }
  }

  function handlePrev() {
    setCurrentStep((prev) => Math.max(0, prev - 1))
  }

  const placement = step.placement ?? "bottom"

  return createPortal(
    <div
      className="fixed inset-0 z-[9999]"
      role="dialog"
      aria-modal="true"
      aria-label={`Tour step ${currentStep + 1} of ${steps.length}`}
    >
      {/* Overlay with cutout */}
      <svg
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      >
        <defs>
          <mask id="tour-mask">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {targetRect && (
              <rect
                x={targetRect.left - 4}
                y={targetRect.top - 4}
                width={targetRect.width + 8}
                height={targetRect.height + 8}
                rx="6"
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width="100%"
          height="100%"
          fill="rgba(0,0,0,0.5)"
          mask="url(#tour-mask)"
        />
      </svg>

      {/* Highlight ring */}
      {targetRect && (
        <div
          className="absolute z-[1] rounded-md ring-2 ring-primary ring-offset-2"
          style={{
            top: targetRect.top - 4,
            left: targetRect.left - 4,
            width: targetRect.width + 8,
            height: targetRect.height + 8,
          }}
          aria-hidden="true"
        />
      )}

      {/* Popover */}
      {targetRect && (
        <div
          className={cn(
            "absolute z-[2] w-80 rounded-lg border bg-background p-4 shadow-lg",
          )}
          style={getPopoverPosition(targetRect, placement)}
        >
          <div className="mb-3">
            <h4 className="text-sm font-semibold text-foreground">
              {step.title}
            </h4>
            <p className="mt-1 text-sm text-muted-foreground">
              {step.description}
            </p>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {currentStep + 1} of {steps.length}
            </span>

            <div className="flex items-center gap-2">
              {onSkip && (
                <Button variant="ghost" size="sm" onClick={onSkip}>
                  Skip
                </Button>
              )}
              {!isFirst && (
                <Button variant="outline" size="sm" onClick={handlePrev}>
                  Previous
                </Button>
              )}
              <Button size="sm" onClick={handleNext}>
                {isLast ? "Finish" : "Next"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}

function getPopoverPosition(
  rect: TargetRect,
  placement: "top" | "bottom" | "left" | "right",
): React.CSSProperties {
  const gap = 12

  switch (placement) {
    case "top":
      return {
        bottom: `calc(100% - ${rect.top - gap}px)`,
        left: rect.left + rect.width / 2 - 160,
      }
    case "bottom":
      return {
        top: rect.top + rect.height + gap,
        left: rect.left + rect.width / 2 - 160,
      }
    case "left":
      return {
        top: rect.top + rect.height / 2 - 60,
        right: `calc(100% - ${rect.left - gap}px)`,
      }
    case "right":
      return {
        top: rect.top + rect.height / 2 - 60,
        left: rect.left + rect.width + gap,
      }
  }
}
