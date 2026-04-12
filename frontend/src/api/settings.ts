export type DojoSettings = {
  dojo_name: string
  logo_url: string | null
  primary_colour: string
}

export const getDojoSettings = async (): Promise<DojoSettings> => {
  const res = await fetch("/api/settings/dojo", { credentials: "include" })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch dojo settings" }
  }
  return res.json() as Promise<DojoSettings>
}

export const updateDojoSettings = async (
  data: Partial<Pick<DojoSettings, "dojo_name" | "primary_colour">>
): Promise<DojoSettings> => {
  const res = await fetch("/api/settings/dojo", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to update dojo settings" }
  }
  return res.json() as Promise<DojoSettings>
}

export const uploadDojoLogo = async (file: File): Promise<{ logo_url: string }> => {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch("/api/settings/logo", {
    method: "POST",
    credentials: "include",
    body: form,
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to upload logo" }
  }
  return res.json() as Promise<{ logo_url: string }>
}
