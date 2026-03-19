import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"

export interface ModelInfo {
  model_id: string
  provider: string
  display_name: string
  max_input_tokens: number
  max_output_tokens: number
  supports_streaming: boolean
  supports_function_calling: boolean
  supports_vision: boolean
  available: boolean
}

export function useModels() {
  return useQuery({
    queryKey: queryKeys.ai.models(),
    queryFn: async ({ signal }) => {
      const data = await api.get("ai/models", { signal }).json<ModelInfo[]>()
      return data ?? []
    },
    staleTime: 5 * 60 * 1000, // models rarely change, cache for 5 min
  })
}
