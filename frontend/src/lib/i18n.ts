import i18n from "i18next"
import { initReactI18next } from "react-i18next"
import HttpBackend from "i18next-http-backend"
import LanguageDetector from "i18next-browser-languagedetector"

export const supportedLanguages = [
  { code: "en", name: "English", nativeName: "English" },
  { code: "de", name: "German", nativeName: "Deutsch" },
  { code: "es", name: "Spanish", nativeName: "Español" },
  { code: "zh", name: "Chinese", nativeName: "中文" },
] as const

export const supportedLngs = supportedLanguages.map((l) => l.code)

export const defaultNS = "common"
export const ns = [
  "common",
  "auth",
  "validation",
  "errors",
  "settings",
  "dashboard",
  "jobs",
  "files",
  "team",
  "api_keys",
  "billing",
  "webhooks",
  "audit_log",
  "chat",
  "notifications",
  "ai",
] as const

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: "en",
    supportedLngs,
    defaultNS,
    ns: [...ns],

    returnNull: false,
    returnEmptyString: false,

    interpolation: {
      escapeValue: false, // React already escapes
    },

    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
    },

    detection: {
      order: ["localStorage", "navigator", "htmlTag"],
      lookupLocalStorage: "i18nextLng",
      caches: ["localStorage"],
    },

    react: {
      useSuspense: true,
    },
  })

// Update HTML lang attribute on language change
i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng
  document.documentElement.dir = "ltr"
})

export default i18n
