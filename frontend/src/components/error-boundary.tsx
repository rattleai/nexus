import { Component, type ErrorInfo, type ReactNode } from "react"
import i18n from "i18next"
import { Button } from "@/components/ui/button"

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Uncaught error:", error, info)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div role="alert" className="min-h-screen flex items-center justify-center p-8">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-bold text-foreground">
              {i18n.t("boundary.title", { ns: "errors" })}
            </h1>
            <p className="text-muted-foreground">
              {i18n.t("boundary.description", { ns: "errors" })}
            </p>
            <Button
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.href = "/"
              }}
            >
              {i18n.t("boundary.reload", { ns: "errors" })}
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
