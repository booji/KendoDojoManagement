import type { ApiError } from "@/api/auth"

export type PasskeyRecord = {
  id: string
  label: string
  aaguid: string | null
  created_at: string
  last_used_at: string | null
}

const throwApiError = async (res: Response, defaultMessage: string): Promise<never> => {
  let message = defaultMessage
  try {
    const body = (await res.json()) as { detail?: string }
    if (body.detail) message = body.detail
  } catch {
    // ignore parse errors
  }
  throw { status: res.status, message } satisfies ApiError
}

export const listPasskeys = async (): Promise<PasskeyRecord[]> => {
  const res = await fetch("/api/auth/passkeys", { credentials: "include" })

  if (res.status === 401) {
    await throwApiError(res, "Not authenticated")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load passkeys")
  }

  return res.json() as Promise<PasskeyRecord[]>
}

export const renamePasskey = async (id: string, label: string): Promise<PasskeyRecord> => {
  const res = await fetch(`/api/auth/passkeys/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ label }),
  })

  if (res.status === 401) {
    await throwApiError(res, "Not authenticated")
  }
  if (res.status === 404) {
    await throwApiError(res, "Passkey not found")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to rename passkey")
  }

  return res.json() as Promise<PasskeyRecord>
}

export const deletePasskey = async (id: string): Promise<void> => {
  const res = await fetch(`/api/auth/passkeys/${id}`, {
    method: "DELETE",
    credentials: "include",
  })

  if (res.status === 400) {
    await throwApiError(res, "You need at least one passkey")
  }
  if (res.status === 401) {
    await throwApiError(res, "Not authenticated")
  }
  if (res.status === 404) {
    await throwApiError(res, "Passkey not found")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to delete passkey")
  }
}
