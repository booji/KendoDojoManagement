import { useEffect, useRef, useState } from "react"
import {
  getSessionTypes,
  updateSessionTypeColour,
  createSessionType,
  deleteSessionType,
} from "@/api/sessions"
import type { SessionType } from "@/api/sessions"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Section } from "@/components/ui/section"
import { EmptyState } from "@/components/ui/empty-state"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Trash2 } from "lucide-react"

type SaveStatus = "idle" | "saving" | "saved" | "error"

// ── Session Types section ─────────────────────────────────────────────────────

export const SessionTypesSection = () => {
  const [sessionTypes, setSessionTypes] = useState<SessionType[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveErrors, setSaveErrors] = useState<Record<string, string | null>>({})
  const [saveStatuses, setSaveStatuses] = useState<Record<string, SaveStatus>>({})
  const [newName, setNewName] = useState("")
  const [addStatus, setAddStatus] = useState<"idle" | "saving" | "error">("idle")
  const [addError, setAddError] = useState<string | null>(null)

  // Deletion: which type is pending confirmation, plus in-flight/error state.
  const [pendingDelete, setPendingDelete] = useState<SessionType | null>(null)
  const [deleteStatus, setDeleteStatus] = useState<"idle" | "deleting">("idle")
  // The safe choice takes focus, so Enter on open never deletes anything.
  const deleteCancelRef = useRef<HTMLButtonElement>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    getSessionTypes()
      .then((types) => {
        setSessionTypes(types)
      })
      .catch((err: unknown) => {
        const msg =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to load session types"
        setLoadError(msg)
      })
  }, [])

  const handleAddSessionType = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setAddStatus("saving")
    setAddError(null)
    try {
      const created = await createSessionType(name)
      setSessionTypes((prev) => (prev !== null ? [...prev, created] : [created]))
      setNewName("")
      setAddStatus("idle")
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to add session type"
      setAddError(msg)
      setAddStatus("error")
    }
  }

  const handleColourChange = async (id: string, colour: string) => {
    setSaveStatuses((prev) => ({ ...prev, [id]: "saving" }))
    setSaveErrors((prev) => ({ ...prev, [id]: null }))
    try {
      const updated = await updateSessionTypeColour(id, colour)
      setSessionTypes((prev) =>
        prev !== null ? prev.map((t) => (t.id === id ? updated : t)) : prev
      )
      setSaveStatuses((prev) => ({ ...prev, [id]: "saved" }))
      setTimeout(() => setSaveStatuses((prev) => ({ ...prev, [id]: "idle" })), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setSaveErrors((prev) => ({ ...prev, [id]: msg }))
      setSaveStatuses((prev) => ({ ...prev, [id]: "error" }))
    }
  }

  const handleConfirmDelete = async () => {
    if (pendingDelete === null) return
    const target = pendingDelete
    setDeleteStatus("deleting")
    setDeleteError(null)
    try {
      await deleteSessionType(target.id)
      setSessionTypes((prev) =>
        prev !== null ? prev.filter((t) => t.id !== target.id) : prev
      )
      setPendingDelete(null)
    } catch (err: unknown) {
      // On 409 the type is still referenced — keep it in the list and show why.
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to delete session type"
      setDeleteError(msg)
    } finally {
      setDeleteStatus("idle")
    }
  }

  if (sessionTypes === null && loadError === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  }

  if (loadError !== null) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {loadError}
      </p>
    )
  }

  const addForm = (
    <form onSubmit={(e) => void handleAddSessionType(e)} className="flex gap-2 items-start pt-2">
      <Input
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        placeholder="New session type name"
        aria-label="New session type name"
        className="flex-1"
        disabled={addStatus === "saving"}
      />
      <Button type="submit" disabled={addStatus === "saving" || newName.trim() === ""}>
        {addStatus === "saving" ? "Adding…" : "Add"}
      </Button>
      {addError !== null && (
        <p className="text-sm text-destructive" role="alert">{addError}</p>
      )}
    </form>
  )

  if (sessionTypes !== null && sessionTypes.length === 0) {
    return (
      <div className="space-y-3">
        <EmptyState message="No session types configured." />
        {addForm}
      </div>
    )
  }

  return (
    <>
    <div className="space-y-4">
      {(sessionTypes ?? []).map((t) => {
        const status = saveStatuses[t.id] ?? "idle"
        const error = saveErrors[t.id] ?? null
        return (
          <div key={t.id} className="space-y-1">
            <Label htmlFor={`session-type-colour-${t.id}`}>{t.name}</Label>
            <div className="flex gap-2 items-center">
              <Input
                id={`session-type-colour-${t.id}`}
                type="color"
                value={t.colour ?? "#4F46E5"}
                onChange={(e) => void handleColourChange(t.id, e.target.value)}
                aria-label={`Colour for ${t.name}`}
                className="h-11 w-16 cursor-pointer rounded-md border border-input p-1 shrink-0"
              />
              <span className="text-sm font-mono text-muted-foreground">
                {t.colour ?? "default"}
              </span>
              <div className="ml-auto flex items-center gap-2">
                {status === "saving" && (
                  <span className="text-sm text-muted-foreground" aria-live="polite">
                    Saving…
                  </span>
                )}
                {status === "saved" && (
                  <span className="text-sm text-green-600 dark:text-green-400" aria-live="polite">
                    Saved!
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 w-9 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    setDeleteError(null)
                    setPendingDelete(t)
                  }}
                  aria-label={`Delete ${t.name}`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
        )
      })}
      {addForm}
    </div>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => {
          if (!o && deleteStatus !== "deleting") {
            setPendingDelete(null)
            setDeleteError(null)
          }
        }}
      >
        <DialogContent initialFocus={deleteCancelRef}>
          <DialogHeader>
            <DialogTitle>Delete session type</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Delete <span className="font-medium text-foreground">{pendingDelete?.name}</span>?
            This cannot be undone.
          </p>
          {deleteError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {deleteError}
            </p>
          )}
          <DialogFooter>
            <Button
              ref={deleteCancelRef}
              variant="outline"
              onClick={() => {
                setPendingDelete(null)
                setDeleteError(null)
              }}
              disabled={deleteStatus === "deleting"}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleConfirmDelete()}
              disabled={deleteStatus === "deleting"}
            >
              {deleteStatus === "deleting" ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
const AdminSessionTypesPage = () => (
  <Section heading="Session Types">
    <SessionTypesSection />
  </Section>
)

export default AdminSessionTypesPage
