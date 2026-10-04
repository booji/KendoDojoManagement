/**
 * Onboarding completes the Member the Account already has (#432): the first
 * Admin named themselves at the setup claim, an invitee was named by the
 * invite, so the form opens with that name and asks for what is missing.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import OnboardingPage from "@/pages/OnboardingPage"

vi.mock("@/api/accounts", () => ({
  getMyMember: vi.fn().mockResolvedValue({
    id: "m1",
    email: "sensei@dojo.test",
    first_name: "Ai",
    surname: "Sato",
    display_name: null,
    dob: null,
    join_date: "2026-10-03",
    membership_status: "active",
    is_coach: false,
    is_first_aider: false,
    emergency_contact_name: "Hanako Sato",
    emergency_contact_phone: "+447700900000",
  }),
  putMyMember: vi.fn(),
}))

describe("OnboardingPage", () => {
  it("opens with the name the Member already has", async () => {
    render(
      <MemoryRouter>
        <OnboardingPage />
      </MemoryRouter>
    )

    expect(await screen.findByDisplayValue("Ai")).toBeInTheDocument()
    expect(screen.getByDisplayValue("Sato")).toBeInTheDocument()
  })

  it("keeps an emergency contact the admin already entered", async () => {
    // Submit sends every field, and a null clears it: an unfilled field here
    // would erase what the admin recorded.
    render(
      <MemoryRouter>
        <OnboardingPage />
      </MemoryRouter>
    )

    expect(await screen.findByDisplayValue("Hanako Sato")).toBeInTheDocument()
    expect(screen.getByDisplayValue("+447700900000")).toBeInTheDocument()
  })
})
