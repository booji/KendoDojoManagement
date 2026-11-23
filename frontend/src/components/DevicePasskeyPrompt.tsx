import { useState } from "react"
import { performPasskeyAdd } from "@/api/auth"
import { errorMessage } from "@/api/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  closeDevicePasskeyOffer,
  dismissDevicePasskeyOffer,
  isDevicePasskeyOffered,
} from "@/lib/devicePasskeyOffer"

// Offers a passkey for this device after a sign-in from a phone (#612).
const DevicePasskeyPrompt = () => {
  const [open, setOpen] = useState(isDevicePasskeyOffered)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dismiss = () => {
    dismissDevicePasskeyOffer()
    setOpen(false)
  }

  const add = async () => {
    setError(null)
    setAdding(true)
    try {
      await performPasskeyAdd()
      closeDevicePasskeyOffer()
      setOpen(false)
    } catch (err) {
      setError(errorMessage(err, "Failed to register passkey"))
    } finally {
      setAdding(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent showCloseButton>
        <DialogHeader>
          <DialogTitle>Add a passkey on this device?</DialogTitle>
          <DialogDescription>
            Add a passkey on this device so you don&apos;t need your phone next time.
          </DialogDescription>
        </DialogHeader>
        {error !== null && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={dismiss} disabled={adding}>
            Not now
          </Button>
          <Button onClick={() => void add()} disabled={adding}>
            {adding ? "Registering…" : "Add passkey"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default DevicePasskeyPrompt
