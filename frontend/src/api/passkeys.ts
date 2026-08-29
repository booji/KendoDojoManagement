import { apiFetch, throwApiError } from "@/api/client"

export type PasskeyRecord = {
  id: string
  label: string
  aaguid: string | null
  created_at: string
  last_used_at: string | null
}

export const listPasskeys = async (): Promise<PasskeyRecord[]> => {
  const res = await apiFetch("/api/auth/passkeys")

  if (res.status === 401) {
    await throwApiError(res, "Not authenticated")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load passkeys")
  }

  return res.json() as Promise<PasskeyRecord[]>
}

export const renamePasskey = async (id: string, label: string): Promise<PasskeyRecord> => {
  const res = await apiFetch(`/api/auth/passkeys/${id}`, { method: "PATCH", body: { label } })

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

export type SecurityStatus = {
  passkey_count: number
}

export const getSecurityStatus = async (): Promise<SecurityStatus> => {
  const res = await apiFetch("/api/auth/security-status")

  if (res.status === 401) {
    await throwApiError(res, "Not authenticated")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load security status")
  }

  return res.json() as Promise<SecurityStatus>
}

export const deletePasskey = async (id: string): Promise<void> => {
  const res = await apiFetch(`/api/auth/passkeys/${id}`, { method: "DELETE" })

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
