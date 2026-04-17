const KEY = "recovery_token"

export const storeRecoveryToken = (token: string): void => {
  sessionStorage.setItem(KEY, token)
}

export const getRecoveryToken = (): string | null => {
  return sessionStorage.getItem(KEY)
}

export const clearRecoveryToken = (): void => {
  sessionStorage.removeItem(KEY)
}

export const isRecoverySession = (): boolean => {
  const token = getRecoveryToken()
  if (!token) return false
  try {
    const payload = JSON.parse(atob(token.split(".")[1])) as Record<string, unknown>
    return payload.recovery_session === true
  } catch {
    return false
  }
}
