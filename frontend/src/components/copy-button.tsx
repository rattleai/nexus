import { useTranslation } from "react-i18next"
import { Check, Copy } from "lucide-react"
import { Button, type ButtonProps } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard"

interface CopyButtonProps extends Omit<ButtonProps, "onClick"> {
  value: string
}

export function CopyButton({ value, ...props }: CopyButtonProps) {
  const { t } = useTranslation()
  const { copied, copy } = useCopyToClipboard()

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => copy(value)}
      aria-label={copied ? t("status.copied") : t("aria.copy_to_clipboard")}
      {...props}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </Button>
  )
}
