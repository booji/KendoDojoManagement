import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { putMyMember } from "@/api/users"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

type FormState = {
  first_name: string
  surname: string
  dob: string
  display_name: string
  emergency_contact_name: string
  emergency_contact_phone: string
}

const EMPTY_FORM: FormState = {
  first_name: "",
  surname: "",
  dob: "",
  display_name: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
}

const OnboardingPage = () => {
  const navigate = useNavigate()
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleChange = <K extends keyof FormState>(key: K, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await putMyMember({
        first_name: form.first_name,
        surname: form.surname,
        dob: form.dob,
        display_name: form.display_name || null,
        emergency_contact_name: form.emergency_contact_name || null,
        emergency_contact_phone: form.emergency_contact_phone || null,
      })
      navigate("/", { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile")
    } finally {
      setSaving(false)
    }
  }

  const isValid =
    form.first_name.trim() !== "" &&
    form.surname.trim() !== "" &&
    form.dob !== ""

  return (
    <div className="min-h-screen flex items-start justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold mb-6 text-center">Complete your profile</h1>
        <Card>
          <CardHeader>
            <CardTitle>Personal details</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5" aria-label="Complete your profile">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label htmlFor="onboarding_first_name">
                    First name <span aria-hidden="true" className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="onboarding_first_name"
                    value={form.first_name}
                    onChange={(e) => handleChange("first_name", e.target.value)}
                    placeholder="Jane"
                    autoComplete="given-name"
                    required
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="onboarding_surname">
                    Surname <span aria-hidden="true" className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="onboarding_surname"
                    value={form.surname}
                    onChange={(e) => handleChange("surname", e.target.value)}
                    placeholder="Smith"
                    autoComplete="family-name"
                    required
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="onboarding_dob">
                    Date of birth <span aria-hidden="true" className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="onboarding_dob"
                    type="date"
                    value={form.dob}
                    onChange={(e) => handleChange("dob", e.target.value)}
                    autoComplete="bday"
                    required
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="onboarding_display_name">Display name</Label>
                  <Input
                    id="onboarding_display_name"
                    value={form.display_name}
                    onChange={(e) => handleChange("display_name", e.target.value)}
                    placeholder="Optional"
                    autoComplete="nickname"
                  />
                </div>

                <div className="space-y-1 sm:col-span-2">
                  <Label htmlFor="onboarding_ec_name">Emergency contact name</Label>
                  <Input
                    id="onboarding_ec_name"
                    value={form.emergency_contact_name}
                    onChange={(e) => handleChange("emergency_contact_name", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>

                <div className="space-y-1 sm:col-span-2">
                  <Label htmlFor="onboarding_ec_phone">Emergency contact phone</Label>
                  <Input
                    id="onboarding_ec_phone"
                    type="tel"
                    value={form.emergency_contact_phone}
                    onChange={(e) => handleChange("emergency_contact_phone", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>
              </div>

              {error !== null && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}

              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={saving || !isValid}
              >
                {saving ? "Saving…" : "Save and continue"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default OnboardingPage
