import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getMe, isApiError } from "@/api/auth"
import type { AccountClaims } from "@/api/auth"
import CalendarView from "@/components/CalendarView"

const HomePage = () => {
  const navigate = useNavigate()
  const [user, setUser] = useState<AccountClaims | null>(null)

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
    <div className="flex flex-col h-screen">
      <CalendarView isAdmin={user.role === "admin"} />
    </div>
  )
}

export default HomePage
