const throwApiError = async (res: Response, defaultMessage: string): Promise<never> => {
  let message = defaultMessage
  try {
    const body = (await res.json()) as { detail?: string }
    if (body.detail) message = body.detail
  } catch {
    // ignore parse errors
  }
  throw { status: res.status, message }
}

export type DojoSettings = {
  dojo_name: string
  logo_url: string | null
  primary_colour: string
  checkin_window_before_minutes: number
  checkin_window_after_minutes: number
  background_image_url: string | null
  login_show_background: boolean
  login_show_logo: boolean
  login_show_name: boolean
}

export type DojoBranding = {
  dojo_name: string | null
  logo_url: string | null
  background_image_url: string | null
  primary_colour: string
}

export const getDojoSettings = async (): Promise<DojoSettings> => {
  const res = await fetch("/api/settings/dojo", { credentials: "include" })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch dojo settings" }
  }
  return res.json() as Promise<DojoSettings>
}

export const getBranding = async (): Promise<DojoBranding> => {
  const res = await fetch("/api/settings/branding")
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch branding" }
  }
  return res.json() as Promise<DojoBranding>
}

export const updateDojoSettings = async (
  data: Partial<
    Pick<
      DojoSettings,
      | "dojo_name"
      | "primary_colour"
      | "checkin_window_before_minutes"
      | "checkin_window_after_minutes"
      | "background_image_url"
      | "login_show_background"
      | "login_show_logo"
      | "login_show_name"
    >
  >
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

export const uploadDojoBackground = async (
  file: File
): Promise<{ background_image_url: string }> => {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch("/api/settings/background", {
    method: "POST",
    credentials: "include",
    body: form,
  })
  if (!res.ok) {
    return throwApiError(res, "Failed to upload background")
  }
  return res.json() as Promise<{ background_image_url: string }>
}
