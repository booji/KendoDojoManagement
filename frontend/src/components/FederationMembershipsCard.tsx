/**
 * A Member's Federation Memberships — list, add, edit, remove.
 *
 * This card is shown in two places: an Admin managing another Member on the
 * Member detail page, and a Member managing their own on the settings page.
 * Those two views differ only in *whose* memberships are being read and
 * written, so that difference — and nothing else — crosses the seam, as a
 * `FederationMembershipStore`:
 *
 *   myFederationMemberships              (a Member's own)
 *   memberFederationMemberships(id)      (an Admin, on any Member)
 *
 * The Federation catalogue itself does not vary between the two views, so it
 * stays a direct call rather than a fifth store method.
 *
 * The two copies this replaced had drifted: only the self-service one filtered
 * the catalogue down to active federations, and only it let you clear a chosen
 * federation. Both behaviours are now the single behaviour.
 */

import { useEffect, useId, useRef, useState } from "react"
import { Pencil, Trash2 } from "lucide-react"

import {
  listFederations,
  type FederationMembershipStore,
  type FederationResponse,
  type MemberFederationResponse,
  type RenewalStatus,
} from "@/api/federations"
import { isApiError } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"

type FederationFormState = {
  federation_id: string
  member_number: string
  renewal_date: string
  search: string
}

const EMPTY_FED_FORM: FederationFormState = {
  federation_id: "",
  member_number: "",
  renewal_date: "",
  search: "",
}

const RenewalBadge = ({ status }: { status: RenewalStatus }) => {
  if (status === "expired") {
    return <Badge variant="destructive">Expired</Badge>
  }
  if (status === "expiring_soon") {
    return <Badge variant="warning">Expiring soon</Badge>
  }
  return null
}

type FederationMembershipsCardProps = {
  store: FederationMembershipStore
}

const FederationMembershipsCard = ({ store }: FederationMembershipsCardProps) => {
  const [memberships, setMemberships] = useState<MemberFederationResponse[] | null>(null)
  const [federations, setFederations] = useState<FederationResponse[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FederationFormState>(EMPTY_FED_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Remove confirm dialog
  const [removeId, setRemoveId] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const searchRef = useRef<HTMLInputElement>(null)

  // Both cards render on the same page in no case today, but ids must still be
  // unique per instance rather than per copy-with-a-prefix.
  const fieldId = useId()
  const searchFieldId = `${fieldId}-search`
  const numberFieldId = `${fieldId}-member-number`
  const renewalFieldId = `${fieldId}-renewal-date`

  useEffect(() => {
    Promise.all([store.list(), listFederations()])
      .then(([mfs, feds]) => {
        setMemberships(mfs)
        setFederations(feds.filter((f) => f.is_active))
      })
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load federations")
      })
  }, [store])

  const fedMap = new Map(federations.map((f) => [f.id, f]))

  const filteredFederations = form.search.trim()
    ? federations.filter(
        (f) =>
          f.name.toLowerCase().includes(form.search.toLowerCase()) ||
          (f.abbreviation ?? "").toLowerCase().includes(form.search.toLowerCase())
      )
    : federations

  const openAdd = () => {
    setForm(EMPTY_FED_FORM)
    setEditingId(null)
    setSaveError(null)
    setDialogOpen(true)
    setTimeout(() => searchRef.current?.focus(), 50)
  }

  const openEdit = (mf: MemberFederationResponse) => {
    setForm({
      federation_id: mf.federation_id,
      member_number: mf.member_number,
      renewal_date: mf.renewal_date ?? "",
      search: fedMap.get(mf.federation_id)?.name ?? "",
    })
    setEditingId(mf.id)
    setSaveError(null)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!form.federation_id || !form.member_number.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      if (editingId !== null) {
        const updated = await store.update(editingId, {
          member_number: form.member_number,
          renewal_date: form.renewal_date || null,
        })
        setMemberships((prev) =>
          prev !== null ? prev.map((m) => (m.id === editingId ? updated : m)) : [updated]
        )
      } else {
        const created = await store.add({
          federation_id: form.federation_id,
          member_number: form.member_number,
          ...(form.renewal_date ? { renewal_date: form.renewal_date } : {}),
        })
        setMemberships((prev) => (prev !== null ? [...prev, created] : [created]))
      }
      setDialogOpen(false)
    } catch (err) {
      setSaveError(isApiError(err) ? err.message : "Failed to save")
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    if (removeId === null) return
    setRemoving(true)
    setRemoveError(null)
    try {
      await store.remove(removeId)
      setMemberships((prev) => (prev !== null ? prev.filter((m) => m.id !== removeId) : []))
      setRemoveId(null)
    } catch (err) {
      setRemoveError(isApiError(err) ? err.message : "Failed to remove")
    } finally {
      setRemoving(false)
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Federations</CardTitle>
          <Button variant="outline" size="sm" onClick={openAdd} aria-label="Add federation membership">
            Add
          </Button>
        </CardHeader>
        <CardContent>
          {loadError !== null ? (
            <p className="text-sm text-destructive" role="alert">{loadError}</p>
          ) : memberships === null ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          ) : memberships.length === 0 ? (
            <p className="text-sm text-muted-foreground">No federation memberships yet.</p>
          ) : (
            <ul className="divide-y divide-border">
              {memberships.map((mf) => {
                const fed = fedMap.get(mf.federation_id)
                return (
                  <li key={mf.id} className="py-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-sm font-medium">{fed?.name ?? mf.federation_id}</p>
                      <p className="text-xs text-muted-foreground">
                        Member #{mf.member_number}
                        {mf.renewal_date !== null && (
                          <> · Renews {mf.renewal_date}</>
                        )}
                      </p>
                      <RenewalBadge status={mf.renewal_status} />
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        onClick={() => openEdit(mf)}
                        aria-label={`Edit ${fed?.name ?? "federation"} membership`}
                      >
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                        onClick={() => { setRemoveError(null); setRemoveId(mf.id) }}
                        aria-label={`Remove ${fed?.name ?? "federation"} membership`}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) setDialogOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId !== null ? "Edit federation membership" : "Add federation membership"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            {/* Federation selector */}
            {editingId === null && (
              <div className="space-y-1">
                <Label htmlFor={searchFieldId}>Federation</Label>
                <Input
                  id={searchFieldId}
                  ref={searchRef}
                  placeholder="Search federations…"
                  value={form.search}
                  onChange={(e) => setForm((prev) => ({ ...prev, search: e.target.value, federation_id: "" }))}
                  autoComplete="off"
                />
                {form.search.trim() !== "" && !form.federation_id && filteredFederations.length > 0 && (
                  <ul className="mt-1 max-h-48 overflow-y-auto rounded-md border border-border bg-popover text-sm shadow-sm">
                    {filteredFederations.map((f) => (
                      <li key={f.id}>
                        <button
                          type="button"
                          className="w-full text-left px-3 py-2 hover:bg-accent hover:text-accent-foreground transition-colors flex items-center gap-2"
                          onClick={() =>
                            setForm((prev) => ({ ...prev, federation_id: f.id, search: f.name }))
                          }
                        >
                          {f.is_pinned && (
                            <span className="text-xs text-muted-foreground shrink-0">★</span>
                          )}
                          <span className="flex-1 min-w-0 truncate">{f.name}</span>
                          {f.abbreviation !== null && (
                            <span className="text-xs text-muted-foreground shrink-0">{f.abbreviation}</span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {filteredFederations.length === 0 && form.search.trim() !== "" && !form.federation_id && (
                  <p className="text-xs text-muted-foreground mt-1">No federations match your search.</p>
                )}
                {form.federation_id && (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground hover:text-foreground mt-1"
                    onClick={() => setForm((prev) => ({ ...prev, federation_id: "", search: "" }))}
                  >
                    ✕ Clear selection
                  </button>
                )}
              </div>
            )}
            {editingId !== null && (
              <div className="space-y-0.5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Federation</p>
                <p className="text-sm">{fedMap.get(form.federation_id)?.name ?? form.federation_id}</p>
              </div>
            )}

            <div className="space-y-1">
              <Label htmlFor={numberFieldId}>Member number</Label>
              <Input
                id={numberFieldId}
                value={form.member_number}
                onChange={(e) => setForm((prev) => ({ ...prev, member_number: e.target.value }))}
                placeholder="e.g. BKA-12345"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor={renewalFieldId}>Renewal date (optional)</Label>
              <Input
                id={renewalFieldId}
                type="date"
                value={form.renewal_date}
                onChange={(e) => setForm((prev) => ({ ...prev, renewal_date: e.target.value }))}
              />
            </div>

            {saveError !== null && (
              <p className="text-sm text-destructive" role="alert">{saveError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleSave()}
              disabled={saving || !form.federation_id || !form.member_number.trim()}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove confirm dialog */}
      <Dialog open={removeId !== null} onOpenChange={(o) => { if (!o) setRemoveId(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove federation membership</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove this federation membership? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {removeError !== null && (
            <p className="text-sm text-destructive" role="alert">{removeError}</p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRemoveId(null)}
              disabled={removing}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleRemove()}
              disabled={removing}
            >
              {removing ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export default FederationMembershipsCard
