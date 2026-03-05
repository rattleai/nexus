export const queryKeys = {
  health: ["health"] as const,
  jobs: {
    all: ["jobs"] as const,
    list: (status?: string) => ["jobs", status] as const,
    detail: (id: string) => ["jobs", id] as const,
  },
  apiKeys: {
    all: ["api-keys"] as const,
    list: () => ["api-keys"] as const,
  },
} as const
