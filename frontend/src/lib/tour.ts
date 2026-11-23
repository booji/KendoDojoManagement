// The guided tour (#609). Lazy-loaded from GuidedTour, with driver.js and its
// stylesheet, so none of it is in the main bundle.
import { driver, type Driver } from "driver.js"
import "driver.js/dist/driver.css"
import "./tour.css"
import type { AccountClaims } from "@/api/auth"
import { markTourSeen } from "./tourSeen"

type Step = {
  path: string
  title: string
  description: string
  // A [data-tour] value. Nav items are in the sidebar, which is always
  // rendered; anything else may still be loading when the page opens.
  target?: string
  nav?: boolean
}

const MEMBER_STEPS: Step[] = [
  {
    path: "/",
    target: "nav-/",
    nav: true,
    title: "Dashboard",
    description: "Your dashboard shows the dojo's calendar of upcoming Sessions.",
  },
  {
    path: "/sessions",
    target: "nav-/sessions",
    nav: true,
    title: "Sessions",
    description: "Every Session is listed here. Check in to a Session from it when you arrive.",
  },
  {
    path: "/sessions",
    target: "calendar-feed",
    title: "Calendar feed",
    description:
      "This button opens your calendar feed URL, with a copy button. Subscribe to it in Google Calendar, Apple Calendar or Outlook.",
  },
  {
    path: "/attendance",
    target: "nav-/attendance",
    nav: true,
    title: "My Attendance",
    description: "Your own Attendance history: every Session you checked in to.",
  },
  {
    path: "/attendance",
    title: "Grades",
    description:
      "Your Grade and Grade History are kept by your dojo's Admins, who record each Promotion.",
  },
  {
    path: "/settings",
    target: "security",
    title: "Settings",
    description:
      "Manage your passkeys and recovery codes here. You can take this tour again from Settings too.",
  },
]

// Every Member step first, then the Admin steps in sidebar order, so the tour
// does not jump between pages (#629). An Admin skips the Member's Grades note
// and meets Grade approval last, inside Admin Settings.
const ADMIN_STEPS: Step[] = [
  ...MEMBER_STEPS.filter((s) => s.title !== "Grades"),
  {
    path: "/members",
    target: "nav-/members",
    nav: true,
    title: "Members",
    description: "Every Member of the dojo: their details, Grade and Attendance.",
  },
  {
    path: "/sessions",
    target: "create-session",
    title: "Create a Session or Series",
    description:
      "Create an Ad-hoc Session here, or a Session Template that generates a whole Series.",
  },
  {
    path: "/reports",
    target: "nav-/reports",
    nav: true,
    title: "Reports",
    description: "Attendance and Grade reports for the dojo.",
  },
  {
    path: "/admin/settings",
    target: "nav-/admin/settings",
    nav: true,
    title: "Admin Settings",
    description:
      "Where every type is configured: Session Types, Grades, Federations and so on, plus invites and the dojo's details.",
  },
  {
    path: "/admin/settings/grades",
    target: "admin-settings-grades",
    title: "Grades",
    description:
      "Each Member's Grade is on their page under Members. Proposed Promotions wait for approval here.",
  },
]

// An element that is not displayed (a nav item in the sidebar collapsed on
// mobile) has no client rects; driver.js then centres the popover.
const visibleTarget = (name: string): Element | undefined => {
  const el = document.querySelector(`[data-tour="${name}"]`)
  return el !== null && el.getClientRects().length > 0 ? el : undefined
}

const TARGET_WAIT_MS = 5000

const waitForTarget = async (name: string): Promise<void> => {
  const deadline = Date.now() + TARGET_WAIT_MS
  while (document.querySelector(`[data-tour="${name}"]`) === null && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50))
  }
}

let active: Driver | null = null

export const startTour = (role: AccountClaims["role"], navigate: (path: string) => void): void => {
  if (active !== null) return
  const steps = role === "admin" ? ADMIN_STEPS : MEMBER_STEPS

  const go = async (d: Driver, index: number) => {
    if (index < 0) return
    if (index >= steps.length) {
      d.destroy()
      return
    }
    const step = steps[index]
    if (window.location.pathname !== step.path) navigate(step.path)
    if (step.target !== undefined && !step.nav) await waitForTarget(step.target)
    if (d.isActive()) d.moveTo(index)
    else d.drive(index)
  }

  const d = driver({
    showProgress: true,
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Done",
    steps: steps.map((s) => ({
      // The cast: driver.js centres the popover when this returns nothing.
      element: s.target === undefined ? undefined : () => visibleTarget(s.target!) as Element,
      popover: { title: s.title, description: s.description },
    })),
    onNextClick: () => void go(d, (d.getActiveIndex() ?? 0) + 1),
    onPrevClick: () => void go(d, (d.getActiveIndex() ?? 0) - 1),
    onDestroyed: () => {
      markTourSeen()
      active = null
    },
  })
  active = d
  void go(d, 0)
}
