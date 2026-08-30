import { apiFetch, throwApiError } from "@/api/client"

export type RecoveryStatus = {
  unused_count: number
  has_set: boolean
}

export type RecoveryCodes = {
  codes: string[]
}

export const getRecoveryStatus = async (): Promise<RecoveryStatus> => {
  const res = await apiFetch("/api/auth/recovery/codes/status")
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (!res.ok) await throwApiError(res, "Failed to load recovery code status")
  return res.json() as Promise<RecoveryStatus>
}

export const generateRecoveryCodes = async (): Promise<RecoveryCodes> => {
  const res = await apiFetch("/api/auth/recovery/codes/generate", { method: "POST" })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (res.status === 409) await throwApiError(res, "Recovery codes already exist — use regenerate instead")
  if (!res.ok) await throwApiError(res, "Failed to generate recovery codes")
  return res.json() as Promise<RecoveryCodes>
}

export const regenerateRecoveryCodes = async (): Promise<RecoveryCodes> => {
  const res = await apiFetch("/api/auth/recovery/codes/regenerate", { method: "POST" })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (!res.ok) await throwApiError(res, "Failed to regenerate recovery codes")
  return res.json() as Promise<RecoveryCodes>
}

export type AdminRecoveryTokenResponse = {
  token: string
}

export const generateAdminRecoveryToken = async (
  userId: string
): Promise<AdminRecoveryTokenResponse> => {
  const res = await apiFetch("/api/auth/recovery/admin-token", { method: "POST", body: { user_id: userId } })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (res.status === 403) await throwApiError(res, "Admin access required")
  if (res.status === 404) await throwApiError(res, "Member not found")
  if (!res.ok) await throwApiError(res, "Failed to generate recovery token")
  return res.json() as Promise<AdminRecoveryTokenResponse>
}
