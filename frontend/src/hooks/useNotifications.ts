import { useEffect, useState } from "react"
import { useLocation } from "react-router-dom"
import type { AccountClaims } from "@/api/auth"
import { listPendingGrades, type PendingGradeEntry } from "@/api/grades"

const POLL_MS = 60_000

/** What is waiting for the user's action, derived live; nothing is stored. */
export const useNotifications = (role: AccountClaims["role"]) => {
  const [items, setItems] = useState<PendingGradeEntry[]>([])
  const { pathname } = useLocation()
  useEffect(() => {
    if (role !== "admin") return
    let timer: ReturnType<typeof setInterval> | undefined
    const refresh = () => listPendingGrades().then(setItems, () => {})
    const sync = () => {
      clearInterval(timer)
      timer = undefined
      if (document.visibilityState === "visible") {
        timer = setInterval(refresh, POLL_MS)
      }
    }
    refresh()
    sync()
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh()
      sync()
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [role, pathname])
  return items
}
