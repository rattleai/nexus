import { useCallback, useState } from "react"

interface TokenUsage {
  inputTokens: number
  outputTokens: number
  totalTokens: number
}

interface UseTokenTrackingOptions {
  costPerInputToken?: number
  costPerOutputToken?: number
}

interface MessageUsage {
  messageId: string
  usage: TokenUsage
}

export function useTokenTracking(options: UseTokenTrackingOptions = {}) {
  const {
    costPerInputToken = 0.000003,
    costPerOutputToken = 0.000015,
  } = options

  const [messageUsage, setMessageUsage] = useState<MessageUsage[]>([])

  const totalUsage: TokenUsage = messageUsage.reduce(
    (acc, m) => ({
      inputTokens: acc.inputTokens + m.usage.inputTokens,
      outputTokens: acc.outputTokens + m.usage.outputTokens,
      totalTokens: acc.totalTokens + m.usage.totalTokens,
    }),
    { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
  )

  const estimatedCost =
    totalUsage.inputTokens * costPerInputToken +
    totalUsage.outputTokens * costPerOutputToken

  const addUsage = useCallback((messageId: string, usage: TokenUsage) => {
    setMessageUsage((prev) => [...prev, { messageId, usage }])
  }, [])

  const resetUsage = useCallback(() => {
    setMessageUsage([])
  }, [])

  return {
    totalUsage,
    estimatedCost,
    messageUsage,
    addUsage,
    resetUsage,
  }
}
