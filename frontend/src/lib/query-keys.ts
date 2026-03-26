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

  providerKeys: {
    all: ["provider-keys"] as const,
    list: () => ["provider-keys", "list"] as const,
  },

  ai: {
    all: ["ai"] as const,
    models: () => ["ai", "models"] as const,
  },

  // ── Product Configurator ──────────────────────────────

  productFamilies: {
    all: ["product-families"] as const,
    list: () => ["product-families", "list"] as const,
    detail: (id: string) => ["product-families", "detail", id] as const,
  },

  products: {
    all: ["products"] as const,
    list: (filters?: Record<string, string>) => ["products", "list", filters] as const,
    detail: (id: string) => ["products", "detail", id] as const,
    versions: (productId: string) => ["products", "versions", productId] as const,
  },

  characteristics: {
    all: ["characteristics"] as const,
    list: (filters?: Record<string, string>) => ["characteristics", "list", filters] as const,
    detail: (id: string) => ["characteristics", "detail", id] as const,
    groups: {
      all: ["characteristics", "groups"] as const,
      list: () => ["characteristics", "groups", "list"] as const,
    },
    assignments: (productId: string) => ["characteristics", "assignments", productId] as const,
    assignmentsRaw: (productId: string) => ["characteristics", "assignments-raw", productId] as const,
  },

  constraints: {
    all: ["constraints"] as const,
    groups: {
      all: ["constraints", "groups"] as const,
      list: (productId?: string) => ["constraints", "groups", "list", productId] as const,
    },
    rules: {
      all: ["constraints", "rules"] as const,
      list: (filters?: Record<string, string>) => ["constraints", "rules", "list", filters] as const,
      detail: (id: string) => ["constraints", "rules", "detail", id] as const,
    },
    tables: {
      all: ["constraints", "tables"] as const,
      list: (productId?: string) => ["constraints", "tables", "list", productId] as const,
    },
    analysis: (productId: string) => ["constraints", "analysis", productId] as const,
  },

  boms: {
    all: ["boms"] as const,
    list: (productId?: string) => ["boms", "list", productId] as const,
    detail: (id: string) => ["boms", "detail", id] as const,
    whereUsed: (partNumber: string) => ["boms", "where-used", partNumber] as const,
  },

  configurator: {
    all: ["configurator"] as const,
    sessions: {
      all: ["configurator", "sessions"] as const,
      list: (filters?: Record<string, string>) => ["configurator", "sessions", "list", filters] as const,
      detail: (id: string) => ["configurator", "sessions", "detail", id] as const,
    },
    templates: {
      all: ["configurator", "templates"] as const,
      list: (productId?: string) => ["configurator", "templates", "list", productId] as const,
      detail: (id: string) => ["configurator", "templates", "detail", id] as const,
    },
    bom: (sessionId: string) => ["configurator", "bom", sessionId] as const,
    pricing: (sessionId: string) => ["configurator", "pricing", sessionId] as const,
    comparison: (ids: string[]) => ["configurator", "comparison", ...ids] as const,
    partFrequency: (filters?: Record<string, string>) => ["configurator", "part-frequency", filters] as const,
  },

  pricingRules: {
    all: ["pricing-rules"] as const,
    list: (productId?: string) => ["pricing-rules", "list", productId] as const,
    detail: (id: string) => ["pricing-rules", "detail", id] as const,
  },
} as const
