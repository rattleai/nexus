import { useCallback, useRef, useState } from "react"

interface PullToRefreshOptions {
  onRefresh: () => Promise<void>
  threshold?: number
  maxPull?: number
}

interface PullToRefreshReturn {
  pullDistance: number
  isPulling: boolean
  isRefreshing: boolean
  handlers: {
    onTouchStart: (e: React.TouchEvent) => void
    onTouchMove: (e: React.TouchEvent) => void
    onTouchEnd: () => void
  }
}

/**
 * Pull-to-refresh gesture hook for mobile.
 * Triggers refresh callback when user pulls down past the threshold.
 */
export function usePullToRefresh({
  onRefresh,
  threshold = 80,
  maxPull = 120,
}: PullToRefreshOptions): PullToRefreshReturn {
  const [pullDistance, setPullDistance] = useState(0)
  const [isPulling, setIsPulling] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const startY = useRef(0)
  const pulling = useRef(false)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    const scrollTop = document.documentElement.scrollTop || document.body.scrollTop
    if (scrollTop <= 0) {
      startY.current = e.touches[0].clientY
      pulling.current = true
    }
  }, [])

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!pulling.current || isRefreshing) return
      const diff = e.touches[0].clientY - startY.current
      if (diff > 0) {
        const distance = Math.min(diff * 0.5, maxPull)
        setPullDistance(distance)
        setIsPulling(true)
      }
    },
    [isRefreshing, maxPull],
  )

  const onTouchEnd = useCallback(async () => {
    if (!pulling.current) return
    pulling.current = false

    if (pullDistance >= threshold && !isRefreshing) {
      setIsRefreshing(true)
      setPullDistance(threshold * 0.5)
      try {
        await onRefresh()
      } finally {
        setIsRefreshing(false)
      }
    }

    setPullDistance(0)
    setIsPulling(false)
  }, [pullDistance, threshold, isRefreshing, onRefresh])

  return {
    pullDistance,
    isPulling,
    isRefreshing,
    handlers: { onTouchStart, onTouchMove, onTouchEnd },
  }
}
