import { useCallback, useEffect, useState } from "react"
import {
  listFederations,
  createFederation,
  updateFederation,
  deactivateFederation,
} from "@/api/federations"
import type { FederationResponse, FederationCreateRequest } from "@/api/federations"
import { isApiError } from "@/api/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Pencil, Pin } from "lucide-react"

// ── Federation Catalogue ──────────────────────────────────────────────────────

const FED_TYPES = ["National", "Regional Body", "Global Body", "Special Status"] as const
const FED_GROUPINGS = ["Africa", "Asia", "Europe", "Oceania", "Pan-Am", "Global"] as const

type CatalogueFedForm = {
  name: string
  abbreviation: string
  iso_code: string
  website: string
  continental_grouping: string
  type: string
  is_pinned: boolean
  is_active: boolean
}

const EMPTY_CAT_FORM: CatalogueFedForm = {
  name: "",
  abbreviation: "",
  iso_code: "",
  website: "",
  continental_grouping: "",
  type: "",
  is_pinned: false,
  is_active: true,
}

const isValidUrl = (s: string): boolean => {
  if (!s) return true
  try {
    const u = new URL(s)
    return u.protocol === "https:" || u.protocol === "http:"
  } catch {
    return false
  }
}

type CatalogueLoadState =
  | { status: "loading" }
  | { status: "ready"; federations: FederationResponse[] }
  | { status: "error"; message: string }

// A settled result is tagged with the filters it was fetched for, so a filter
// change reads as "loading" during render instead of needing an effect to
// synchronously reset the state.
type SettledCatalogue = Exclude<CatalogueLoadState, { status: "loading" }> & {
  filters: string
}

export const AdminFederationCatalogue = () => {
  const [catResult, setCatResult] = useState<SettledCatalogue | null>(null)
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [groupingFilter, setGroupingFilter] = useState("")

  const [modalOpen, setModalOpen] = useState(false)
  const [editingFed, setEditingFed] = useState<FederationResponse | null>(null)
  const [catForm, setCatForm] = useState<CatalogueFedForm>(EMPTY_CAT_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [formSaving, setFormSaving] = useState(false)

  const [toggleError, setToggleError] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  const filterKey = `${debouncedSearch}|${typeFilter}|${groupingFilter}`
  const catState: CatalogueLoadState =
    catResult && catResult.filters === filterKey ? catResult : { status: "loading" }

  const loadFederations = useCallback(() => {
    listFederations({
      search: debouncedSearch || undefined,
      type: typeFilter || undefined,
      continental_grouping: groupingFilter || undefined,
    })
      .then((feds) =>
        setCatResult({ status: "ready", federations: feds, filters: filterKey })
      )
      .catch((err: unknown) => {
        setCatResult({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load federations",
          filters: filterKey,
        })
      })
  }, [debouncedSearch, typeFilter, groupingFilter, filterKey])

  useEffect(() => {
    loadFederations()
  }, [loadFederations])

  const openAdd = () => {
    setCatForm(EMPTY_CAT_FORM)
    setEditingFed(null)
    setFormError(null)
    setModalOpen(true)
  }

  const openEdit = (fed: FederationResponse) => {
    setCatForm({
      name: fed.name,
      abbreviation: fed.abbreviation ?? "",
      iso_code: fed.iso_code ?? "",
      website: fed.website ?? "",
      continental_grouping: fed.continental_grouping ?? "",
      type: fed.type ?? "",
      is_pinned: fed.is_pinned,
      is_active: fed.is_active,
    })
    setEditingFed(fed)
    setFormError(null)
    setModalOpen(true)
  }

  const handleFormSave = async () => {
    if (!catForm.name.trim()) {
      setFormError("Name is required")
      return
    }
    if (!isValidUrl(catForm.website)) {
      setFormError("Website must be a valid URL (e.g. https://example.org)")
      return
    }
    setFormSaving(true)
    setFormError(null)
    try {
      const body: FederationCreateRequest = {
        name: catForm.name.trim(),
        // null, not undefined: on edit, a field emptied in the form must clear
        // the stored value, and JSON drops an undefined key (#585).
        abbreviation: catForm.abbreviation.trim() || null,
        iso_code: catForm.iso_code.trim() || null,
        website: catForm.website.trim() || null,
        continental_grouping: catForm.continental_grouping || null,
        type: catForm.type || null,
        is_pinned: catForm.is_pinned,
        is_active: catForm.is_active,
      }
      if (editingFed !== null) {
        await updateFederation(editingFed.id, body)
      } else {
        await createFederation(body)
      }
      setModalOpen(false)
      loadFederations()
    } catch (err) {
      setFormError(isApiError(err) ? err.message : "Failed to save")
    } finally {
      setFormSaving(false)
    }
  }

  const handleTogglePin = async (fed: FederationResponse) => {
    setToggleError(null)
    try {
      await updateFederation(fed.id, { is_pinned: !fed.is_pinned })
      loadFederations()
    } catch (err) {
      setToggleError(isApiError(err) ? err.message : "Failed to update pin")
    }
  }

  const handleToggleActive = async (fed: FederationResponse) => {
    setToggleError(null)
    try {
      if (fed.is_active) {
        await deactivateFederation(fed.id)
      } else {
        await updateFederation(fed.id, { is_active: true })
      }
      loadFederations()
    } catch (err) {
      setToggleError(isApiError(err) ? err.message : "Failed to update status")
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 flex-wrap">
          <CardTitle>Federation Catalogue</CardTitle>
          <Button variant="outline" size="sm" onClick={openAdd}>
            Add federation
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input
              placeholder="Search by name or abbreviation…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 min-w-48"
              aria-label="Search federations"
            />
            <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v ?? "")}>
              <SelectTrigger className="w-44" aria-label="Filter by type">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All types</SelectItem>
                {FED_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={groupingFilter} onValueChange={(v) => setGroupingFilter(v ?? "")}>
              <SelectTrigger className="w-44" aria-label="Filter by region">
                <SelectValue placeholder="All regions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All regions</SelectItem>
                {FED_GROUPINGS.map((g) => (
                  <SelectItem key={g} value={g}>{g}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {toggleError !== null && (
            <p className="text-sm text-destructive" role="alert">{toggleError}</p>
          )}

          {catState.status === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          )}

          {catState.status === "error" && (
            <p className="text-sm text-destructive" role="alert">{catState.message}</p>
          )}

          {catState.status === "ready" && (
            catState.federations.length === 0 ? (
              // Filtering is server-side, so an empty list only means the
              // catalogue itself is empty when nothing is filtering it.
              debouncedSearch === "" && typeFilter === "" && groupingFilter === "" ? (
                <EmptyState
                  message={
                    <>
                      No federations yet. Add the ones your members belong to — the{" "}
                      <a
                        href="https://www.kendo-fik.org/organization/affiliate"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline underline-offset-4"
                      >
                        FIK affiliate list
                      </a>{" "}
                      has their official names, abbreviations and websites.
                    </>
                  }
                />
              ) : (
                <EmptyState message="No federations found." />
              )
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Abbr.</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Region</TableHead>
                      <TableHead>Website</TableHead>
                      <TableHead className="text-center">Pinned</TableHead>
                      <TableHead className="text-center">Active</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {catState.federations.map((fed) => (
                      <TableRow
                        key={fed.id}
                        className={!fed.is_active ? "opacity-50" : undefined}
                      >
                        <TableCell className="font-medium max-w-48 truncate">
                          <span className="flex items-center gap-1.5">
                            {fed.name}
                            {!fed.is_active && (
                              <Badge variant="secondary" className="text-xs">Inactive</Badge>
                            )}
                          </span>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {fed.abbreviation ?? "—"}
                        </TableCell>
                        <TableCell>{fed.type ?? "—"}</TableCell>
                        <TableCell>{fed.continental_grouping ?? "—"}</TableCell>
                        <TableCell className="max-w-40">
                          {fed.website !== null && /^https?:\/\//i.test(fed.website) ? (
                            <a
                              href={fed.website}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary underline-offset-4 hover:underline truncate block max-w-36"
                              title={fed.website}
                            >
                              {fed.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
                            </a>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          <button
                            type="button"
                            onClick={() => void handleTogglePin(fed)}
                            aria-label={fed.is_pinned ? "Unpin federation" : "Pin federation"}
                            className={[
                              "inline-flex items-center justify-center rounded p-1 transition-colors hover:bg-accent",
                              fed.is_pinned
                                ? "text-primary"
                                : "text-muted-foreground",
                            ].join(" ")}
                          >
                            <Pin className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </TableCell>
                        <TableCell className="text-center">
                          <Switch
                            checked={fed.is_active}
                            onCheckedChange={() => void handleToggleActive(fed)}
                            aria-label={fed.is_active ? "Deactivate federation" : "Reactivate federation"}
                          />
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            onClick={() => openEdit(fed)}
                            aria-label={`Edit ${fed.name}`}
                          >
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )
          )}
        </CardContent>
      </Card>

      <Dialog open={modalOpen} onOpenChange={(o) => { if (!o) setModalOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingFed !== null ? "Edit federation" : "Add federation"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1">
              <Label htmlFor="cat_fed_name">Name <span className="text-destructive">*</span></Label>
              <Input
                id="cat_fed_name"
                value={catForm.name}
                onChange={(e) => setCatForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="e.g. British Kendo Association"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="cat_fed_abbr">Abbreviation</Label>
                <Input
                  id="cat_fed_abbr"
                  value={catForm.abbreviation}
                  onChange={(e) => setCatForm((p) => ({ ...p, abbreviation: e.target.value }))}
                  placeholder="e.g. BKA"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="cat_fed_iso">ISO code</Label>
                <Input
                  id="cat_fed_iso"
                  value={catForm.iso_code}
                  onChange={(e) => setCatForm((p) => ({ ...p, iso_code: e.target.value }))}
                  placeholder="e.g. GB"
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="cat_fed_website">Website</Label>
              <Input
                id="cat_fed_website"
                type="url"
                value={catForm.website}
                onChange={(e) => setCatForm((p) => ({ ...p, website: e.target.value }))}
                placeholder="https://example.org"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="cat_fed_type">Type</Label>
                <Select
                  value={catForm.type}
                  onValueChange={(v) => setCatForm((p) => ({ ...p, type: v ?? "" }))}
                >
                  <SelectTrigger id="cat_fed_type" className="w-full">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    {FED_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="cat_fed_grouping">Region</Label>
                <Select
                  value={catForm.continental_grouping}
                  onValueChange={(v) => setCatForm((p) => ({ ...p, continental_grouping: v ?? "" }))}
                >
                  <SelectTrigger id="cat_fed_grouping" className="w-full">
                    <SelectValue placeholder="Select region" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    {FED_GROUPINGS.map((g) => (
                      <SelectItem key={g} value={g}>{g}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <Switch
                  id="cat_fed_pinned"
                  checked={catForm.is_pinned}
                  onCheckedChange={(v) => setCatForm((p) => ({ ...p, is_pinned: v }))}
                />
                <Label htmlFor="cat_fed_pinned">Pinned</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="cat_fed_active"
                  checked={catForm.is_active}
                  onCheckedChange={(v) => setCatForm((p) => ({ ...p, is_active: v }))}
                />
                <Label htmlFor="cat_fed_active">Active</Label>
              </div>
            </div>
            {formError !== null && (
              <p className="text-sm text-destructive" role="alert">{formError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setModalOpen(false)}
              disabled={formSaving}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleFormSave()}
              disabled={formSaving || !catForm.name.trim()}
            >
              {formSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
const AdminFederationsPage = () => (
  <Section heading="Federations">
    <AdminFederationCatalogue />
  </Section>
)

export default AdminFederationsPage
