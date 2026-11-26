import { useEffect } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import type { AccountClaims } from "@/api/auth"
import { isTourSeen } from "@/lib/tourSeen"

type GuidedTourProps = {
  role: AccountClaims["role"]
  // Held back while another dialog is open, so the two never stack.
  paused: boolean
}

// Starts the guided tour (#609) on the Dashboard the first time this device
// signs in. Only the Dashboard: a first sign-in can land on onboarding or a
// check-in, and the tour must not take the user away from either.
const GuidedTour = ({ role, paused }: GuidedTourProps) => {
  const { pathname } = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    if (paused || pathname !== "/" || isTourSeen()) return
    void import("@/lib/tour").then(({ startTour }) => startTour(role, navigate))
  }, [paused, pathname, role, navigate])

  return null
}

export default GuidedTour
