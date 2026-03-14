import "i18next"

import type common from "../../public/locales/en/common.json"
import type auth from "../../public/locales/en/auth.json"
import type validation from "../../public/locales/en/validation.json"
import type errors from "../../public/locales/en/errors.json"
import type settings from "../../public/locales/en/settings.json"
import type dashboard from "../../public/locales/en/dashboard.json"
import type jobs from "../../public/locales/en/jobs.json"
import type files from "../../public/locales/en/files.json"
import type team from "../../public/locales/en/team.json"
import type api_keys from "../../public/locales/en/api_keys.json"
import type billing from "../../public/locales/en/billing.json"
import type webhooks from "../../public/locales/en/webhooks.json"
import type audit_log from "../../public/locales/en/audit_log.json"
import type chat from "../../public/locales/en/chat.json"
import type notifications from "../../public/locales/en/notifications.json"
import type ai from "../../public/locales/en/ai.json"

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common"
    // Return string to avoid ReactI18NextChildren conflicts with React 19
    returnNull: false
    returnEmptyString: false
    // Disable strict key checking to allow cross-namespace refs and dynamic keys
    nsSeparator: ":"
    resources: {
      common: typeof common
      auth: typeof auth
      validation: typeof validation
      errors: typeof errors
      settings: typeof settings
      dashboard: typeof dashboard
      jobs: typeof jobs
      files: typeof files
      team: typeof team
      api_keys: typeof api_keys
      billing: typeof billing
      webhooks: typeof webhooks
      audit_log: typeof audit_log
      chat: typeof chat
      notifications: typeof notifications
      ai: typeof ai
    }
  }
}
