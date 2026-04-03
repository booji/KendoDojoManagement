export type RegisterRequest = {
  email: string
  password: string
}

export type RegisterResponse = {
  sub: string
  email: string
  role: "admin" | "member"
  is_active: boolean
}

export type LoginRequest = {
  email: string
  password: string
}

export type LoginResponse = {
  detail: string
}

export type UserClaims = {
  sub: string
  email: string
  role: "admin" | "member"
  is_active: boolean
}

export type ApiError = {
  status: number
  message: string
}

const isApiError = (e: unknown): e is ApiError =>
  typeof e === "object" && e !== null && "status" in e && "message" in e

export { isApiError }

export const registerWithPassword = async (
  data: RegisterRequest
): Promise<RegisterResponse> => {
  const res = await fetch("/api/auth/register/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })

  if (res.status === 409) {
    throw { status: 409, message: "Email already registered" } satisfies ApiError
  }
  if (res.status === 422) {
    throw { status: 422, message: "Invalid email or password format" } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Registration failed" } satisfies ApiError
  }

  return res.json() as Promise<RegisterResponse>
}

export const loginWithPassword = async (
  data: LoginRequest
): Promise<LoginResponse> => {
  const res = await fetch("/api/auth/login/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })

  if (res.status === 401) {
    throw { status: 401, message: "Invalid credentials" } satisfies ApiError
  }
  if (res.status === 403) {
    throw { status: 403, message: "Account is deactivated" } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Login failed" } satisfies ApiError
  }

  return res.json() as Promise<LoginResponse>
}

export const getMe = async (): Promise<UserClaims> => {
  const res = await fetch("/api/auth/me", {
    credentials: "include",
  })

  if (res.status === 401 || res.status === 403) {
    throw { status: res.status, message: "Not authenticated" } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch user" } satisfies ApiError
  }

  return res.json() as Promise<UserClaims>
}

export const logout = async (): Promise<void> => {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "include",
  })
}
