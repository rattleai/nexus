import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/globals.css"
import "@/lib/i18n"
import { App } from "./app"
import { initWebVitals } from "@/lib/web-vitals"

const rootEl = document.getElementById("root")
if (!rootEl) throw new Error("Root element #root not found")

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Initialize Core Web Vitals reporting (non-blocking, async)
initWebVitals()
