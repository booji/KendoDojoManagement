import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getMe, isApiError } from "@/api/auth"
import type { UserClaims } from "@/api/auth"

const HomePage = () => {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserClaims | null>(null)

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch((err: unknown) => {
        if (isApiError(err) && (err.status === 401 || err.status === 403)) {
          navigate("/login", { replace: true })
        } else {
          navigate("/login", { replace: true })
        }
      })
  }, [navigate])

  if (user === null) {
    return null
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <h1 className="text-2xl font-semibold">Welcome, {user.email}</h1>
    </div>
  )
}

export default HomePage
