import { useEffect, useState } from "react"
import { getMyMember, updateMyMember } from "@/api/members"
import type { MemberResponse, MyMemberUpdateRequest } from "@/api/members"
import { isApiError } from "@/api/auth"
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

// ── Page ──────────────────────────────────────────────────────────────────────

type LoadState =
  | { status: "loading" }
  | { status: "ready"; member: MemberResponse | null }
  | { status: "error"; message: string }

const SettingsPage = () => {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" })
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
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

  const handleChange = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setSaveSuccess(false)
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveError(null)
    setSaveSuccess(false)
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
      setSaveSuccess(true)
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
                  placeholder="Leave blank to keep unchanged"
                  autoComplete="bday"
                />
                {loadState.member !== null && form.dob === "" && (
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

            {saveSuccess && (
              <p
                className="text-sm text-green-700 dark:text-green-400"
                role="status"
                aria-live="polite"
              >
                Details saved successfully.
              </p>
            )}

            {saveError !== null && (
              <p className="text-sm text-destructive" role="alert">
                {saveError}
              </p>
            )}

            <div className="flex justify-end pt-1">
              <Button
                type="submit"
                size="lg"
                disabled={saving}
                aria-label="Save personal details"
                className="w-full sm:w-auto"
              >
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export default SettingsPage
