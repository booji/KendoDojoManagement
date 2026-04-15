import type { ApiError } from "@/api/auth"

export type RecoveryStatus = {
  unused_count: number
  has_set: boolean
}

export type RecoveryCodes = {
  codes: string[]
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

export const getRecoveryStatus = async (): Promise<RecoveryStatus> => {
  const res = await fetch("/api/auth/recovery/codes/status", { credentials: "include" })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (!res.ok) await throwApiError(res, "Failed to load recovery code status")
  return res.json() as Promise<RecoveryStatus>
}

export const generateRecoveryCodes = async (): Promise<RecoveryCodes> => {
  const res = await fetch("/api/auth/recovery/codes/generate", {
    method: "POST",
    credentials: "include",
  })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (res.status === 409) await throwApiError(res, "Recovery codes already exist — use regenerate instead")
  if (!res.ok) await throwApiError(res, "Failed to generate recovery codes")
  return res.json() as Promise<RecoveryCodes>
}

export const regenerateRecoveryCodes = async (): Promise<RecoveryCodes> => {
  const res = await fetch("/api/auth/recovery/codes/regenerate", {
    method: "POST",
    credentials: "include",
  })
  if (res.status === 401) await throwApiError(res, "Not authenticated")
  if (!res.ok) await throwApiError(res, "Failed to regenerate recovery codes")
  return res.json() as Promise<RecoveryCodes>
}
