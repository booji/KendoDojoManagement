import { useEffect, useState } from "react"
import { getMyMember, updateMyMember } from "@/api/members"
import type { MemberResponse, MyMemberUpdateRequest } from "@/api/members"
import { isApiError } from "@/api/auth"
import { useThemeContext } from "@/contexts/ThemeProvider"
import type { Theme } from "@/contexts/ThemeProvider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

// ── Form state ────────────────────────────────────────────────────────────────

type FormState = {
  full_name: string
  dob: string
  emergency_contact_name: string
  emergency_contact_phone: string
  federation_number: string
}

const EMPTY_FORM: FormState = {
  full_name: "",
  dob: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  federation_number: "",
}

const memberToForm = (m: MemberResponse): FormState => ({
  full_name: m.full_name ?? "",
  dob: "",  // dob is not returned by the API — leave blank to avoid overwriting
  emergency_contact_name: m.emergency_contact_name ?? "",
  emergency_contact_phone: m.emergency_contact_phone ?? "",
  federation_number: m.federation_number ?? "",
})

// ── Profile summary (read-only) ───────────────────────────────────────────────

const Field = ({ label, value }: { label: string; value: string | null | undefined }) => (
  <div className="space-y-0.5">
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="text-sm">{value ?? "—"}</dd>
  </div>
)

const ProfileSummary = ({
  member,
  onEdit,
}: {
  member: MemberResponse | null
  onEdit: () => void
}) => {
  if (member === null) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Personal Details</CardTitle>
          <Button variant="outline" size="sm" onClick={onEdit}>
            Set up profile
          </Button>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No profile set up yet.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Personal Details</CardTitle>
        <Button variant="outline" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Full name" value={member.full_name} />
          <Field label="Email" value={member.email} />
          <Field label="Date of birth" value={null} />
          <Field label="Join date" value={member.join_date} />
          <Field label="Membership status" value={member.membership_status} />
          <Field label="Federation number" value={member.federation_number} />
          <Field label="Emergency contact" value={member.emergency_contact_name} />
          <Field label="Emergency contact phone" value={member.emergency_contact_phone} />
        </dl>
        {(member.is_coach || member.is_first_aider || member.is_minor) && (
          <div className="flex gap-2 flex-wrap mt-4">
            {member.is_coach && <Badge>Coach</Badge>}
            {member.is_first_aider && <Badge>First aider</Badge>}
            {member.is_minor && <Badge variant="secondary">Minor</Badge>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type LoadState =
  | { status: "loading" }
  | { status: "ready"; member: MemberResponse | null }
  | { status: "error"; message: string }

const SettingsPage = () => {
  const { theme, setTheme } = useThemeContext()
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" })
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    getMyMember()
      .then((member) => {
        setLoadState({ status: "ready", member })
        setForm(member !== null ? memberToForm(member) : EMPTY_FORM)
      })
      .catch((err: unknown) => {
        setLoadState({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load your details",
        })
      })
  }, [])

  const handleEdit = () => {
    if (loadState.status === "ready") {
      setForm(loadState.member !== null ? memberToForm(loadState.member) : EMPTY_FORM)
    }
    setSaveError(null)
    setEditing(true)
  }

  const handleCancel = () => {
    setSaveError(null)
    setEditing(false)
  }

  const handleChange = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveError(null)
    setSaving(true)

    const payload: MyMemberUpdateRequest = {
      full_name: form.full_name || undefined,
      emergency_contact_name: form.emergency_contact_name || null,
      emergency_contact_phone: form.emergency_contact_phone || null,
      federation_number: form.federation_number || null,
      ...(form.dob ? { dob: form.dob } : {}),
    }

    try {
      const updated = await updateMyMember(payload)
      setLoadState({ status: "ready", member: updated })
      setEditing(false)
    } catch (err) {
      setSaveError(isApiError(err) ? err.message : "Failed to save your details")
    } finally {
      setSaving(false)
    }
  }

  if (loadState.status === "loading") {
    return (
      <div className="px-4 py-6 max-w-2xl mx-auto space-y-4">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }

  if (loadState.status === "error") {
    return (
      <div className="px-4 py-6 max-w-2xl mx-auto">
        <h1 className="text-xl font-semibold mb-4">Settings</h1>
        <p className="text-sm text-destructive" role="alert">
          {loadState.message}
        </p>
      </div>
    )
  }

  return (
    <div className="px-4 py-6 max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      {!editing ? (
        <ProfileSummary member={loadState.member} onEdit={handleEdit} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Personal Details</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5" aria-label="Personal details form">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1 sm:col-span-2">
                  <Label htmlFor="settings_full_name">Full name</Label>
                  <Input
                    id="settings_full_name"
                    value={form.full_name}
                    onChange={(e) => handleChange("full_name", e.target.value)}
                    placeholder="Your full name"
                    autoComplete="name"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_dob">Date of birth</Label>
                  <Input
                    id="settings_dob"
                    type="date"
                    value={form.dob}
                    onChange={(e) => handleChange("dob", e.target.value)}
                    autoComplete="bday"
                  />
                  {form.dob === "" && (
                    <p className="text-xs text-muted-foreground">
                      Leave blank to keep your existing date of birth.
                    </p>
                  )}
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_federation_number">Federation number</Label>
                  <Input
                    id="settings_federation_number"
                    value={form.federation_number}
                    onChange={(e) => handleChange("federation_number", e.target.value)}
                    placeholder="Optional"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_ec_name">Emergency contact name</Label>
                  <Input
                    id="settings_ec_name"
                    value={form.emergency_contact_name}
                    onChange={(e) => handleChange("emergency_contact_name", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_ec_phone">Emergency contact phone</Label>
                  <Input
                    id="settings_ec_phone"
                    type="tel"
                    value={form.emergency_contact_phone}
                    onChange={(e) => handleChange("emergency_contact_phone", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>
              </div>

              {saveError !== null && (
                <p className="text-sm text-destructive" role="alert">
                  {saveError}
                </p>
              )}

              <div className="flex justify-end gap-3 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={handleCancel}
                  disabled={saving}
                  className="w-full sm:w-auto"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="lg"
                  disabled={saving}
                  className="w-full sm:w-auto"
                >
                  {saving ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">Appearance</h2>
        </CardHeader>
        <CardContent>
          <div role="group" aria-label="Theme" className="flex gap-2 flex-wrap">
            {(["light", "system", "dark"] as const).map((t: Theme) => (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                aria-pressed={theme === t}
                className={[
                  "rounded-md px-4 py-2 text-sm font-medium border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  theme === t
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-foreground border-border hover:bg-accent hover:text-accent-foreground",
                ].join(" ")}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default SettingsPage
