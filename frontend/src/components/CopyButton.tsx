import { useEffect, useRef, useState } from "react"
import { Copy } from "lucide-react"

import { Button } from "@/components/ui/button"

const CONFIRMATION_MS = 2000

type CopyButtonProps = {
  /** The text placed on the clipboard. */
  value: string
  /** Accessible name, e.g. "Copy check-in link" — several of these can share a page. */
  label: string
  className?: string
}

/**
 * Copy `value` to the clipboard, confirming briefly in the label.
 *
 * A clipboard write can reject — an insecure context, or a denied permission —
 * and there is nothing useful to say when it does: every caller renders the
 * value next to this button, so it stays selectable by hand. The rejection is
 * therefore swallowed and the label simply never changes.
 */
const CopyButton = ({ value, label, className }: CopyButtonProps) => {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timer.current !== null) clearTimeout(timer.current)
    }
  }, [])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      return
    }
    setCopied(true)
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopied(false), CONFIRMATION_MS)
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={() => void handleCopy()}
      aria-label={label}
    >
      <Copy className="h-4 w-4 mr-1.5" aria-hidden="true" />
      {copied ? "Copied!" : "Copy"}
    </Button>
  )
}

export default CopyButton
