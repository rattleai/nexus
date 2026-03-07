/**
 * Centralized React Query key factory.
 * Prevents key duplication and enables targeted cache invalidation.
 */
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

  files: {
    all: ["files"] as const,
    list: () => ["files", "list"] as const,
    detail: (id: string) => ["files", "detail", id] as const,
  },

  billing: {
    all: ["billing"] as const,
    subscription: () => ["billing", "subscription"] as const,
    plans: () => ["billing", "plans"] as const,
    invoices: () => ["billing", "invoices"] as const,
    portal: () => ["billing", "portal"] as const,
  },

  team: {
    all: ["team"] as const,
    members: () => ["team", "members"] as const,
    invitations: () => ["team", "invitations"] as const,
  },

  webhooks: {
    all: ["webhooks"] as const,
    list: () => ["webhooks", "list"] as const,
    detail: (id: string) => ["webhooks", "detail", id] as const,
    deliveries: (endpointId: string) => ["webhooks", "deliveries", endpointId] as const,
  },

  notifications: {
    all: ["notifications"] as const,
    list: () => ["notifications", "list"] as const,
    unread: () => ["notifications", "unread"] as const,
  },

  auditLogs: {
    all: ["audit-logs"] as const,
    list: (filters?: Record<string, string>) => ["audit-logs", "list", filters] as const,
  },

  usage: {
    all: ["usage"] as const,
    current: () => ["usage", "current"] as const,
  },

  tenants: {
    all: ["tenants"] as const,
    current: () => ["tenants", "current"] as const,
  },
} as const
