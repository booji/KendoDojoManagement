import type { ApiError } from "@/api/auth"

export type Theme = "light" | "dark" | "system"
export type Preferences = { theme: Theme }

export const getPreferences = async (): Promise<Preferences> => {
  const res = await fetch("/api/users/me/preferences", {
    credentials: "include",
  })
  if (res.status === 401 || res.status === 403) {
    throw { status: res.status, message: "Not authenticated" } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch preferences" } satisfies ApiError
  }
  return res.json() as Promise<Preferences>
}

export const updatePreferences = async (theme: Theme): Promise<Preferences> => {
  const res = await fetch("/api/users/me/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ theme }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to update preferences" } satisfies ApiError
  }
  return res.json() as Promise<Preferences>
}
