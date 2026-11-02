import { apiFetch, request, throwApiError } from "@/api/client"

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
  return request<DojoSettings>("/api/settings/dojo", { errorMessage: "Failed to fetch dojo settings" })
}

// Admin-only: the Version the server is running, `dev` outside a release (#556).
export const getVersion = async (): Promise<{ version: string }> => {
  return request<{ version: string }>("/api/settings/version", { errorMessage: "Failed to fetch version" })
}

export const getBranding = async (): Promise<DojoBranding> => {
  return request<DojoBranding>("/api/settings/branding", { errorMessage: "Failed to fetch branding" })
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
  return request<DojoSettings>("/api/settings/dojo", { method: "PUT", body: data, errorMessage: "Failed to update dojo settings" })
}

export const uploadDojoLogo = async (file: File): Promise<{ logo_url: string }> => {
  const form = new FormData()
  form.append("file", file)
  return request<{ logo_url: string }>("/api/settings/logo", { method: "POST", body: form, errorMessage: "Failed to upload logo" })
}

export const uploadDojoBackground = async (
  file: File
): Promise<{ background_image_url: string }> => {
  const form = new FormData()
  form.append("file", file)
  const res = await apiFetch("/api/settings/background", { method: "POST", body: form })
  if (!res.ok) {
    return throwApiError(res, "Failed to upload background")
  }
  return res.json() as Promise<{ background_image_url: string }>
}
