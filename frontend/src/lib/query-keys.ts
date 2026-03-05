export const queryKeys = {
  health: ["health"] as const,
  jobs: {
    all: ["jobs"] as const,
    list: (status?: string) => ["jobs", "list", status] as const,
    detail: (id: string) => ["jobs", "detail", id] as const,
  },
  apiKeys: {
    all: ["api-keys"] as const,
    list: () => ["api-keys", "list"] as const,
  },
} as const
