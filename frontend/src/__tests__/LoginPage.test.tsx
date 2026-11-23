/**
 * Unit tests for LoginPage login-screen branding (issue #213).
 *
 * Acceptance criteria covered:
 *   - renders dojo name, logo, and background (with dark scrim) when the
 *     branding response includes them
 *   - falls back to today's bare card when the branding response is all-null
 *   - falls back to today's bare card when the branding fetch rejects
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import LoginPage from "@/pages/LoginPage"
import { performPasskeyLogin } from "@/api/auth"
import { isDevicePasskeyOffered } from "@/lib/devicePasskeyOffer"

// ── Mock @/api/settings ────────────────────────────────────────────────────

const getBrandingMock = vi.fn()

vi.mock("@/api/settings", () => ({
  getBranding: () => getBrandingMock(),
}))

// ── Mock @/api/auth ─────────────────────────────────────────────────────────

vi.mock("@/api/auth", () => ({
  performPasskeyLogin: vi.fn(),
  isApiError: (e: unknown): e is { status: number; message: string } =>
    typeof e === "object" && e !== null && "message" in e,
}))

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <LoginPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("branding present", () => {
  it("renders dojo name, logo, and a dark scrim over the background", async () => {
    getBrandingMock.mockResolvedValue({
      dojo_name: "Riverside Kendo Dojo",
      logo_url: "/static/logos/abc.png",
      background_image_url: "/static/backgrounds/xyz.png",
      primary_colour: "#1D4ED8",
    })

    renderLoginPage()

    await waitFor(() => {
      expect(screen.getByText("Riverside Kendo Dojo")).toBeInTheDocument()
    })

    expect(screen.getByAltText("Dojo logo")).toHaveAttribute(
      "src",
      "/static/logos/abc.png",
    )

    // Sign-in card must still be present and legible.
    expect(screen.getByText("Sign in")).toBeInTheDocument()

    // A dark scrim overlay must be present when a background is shown.
    const scrim = document.querySelector(".bg-black\\/40")
    expect(scrim).not.toBeNull()
  })
})

describe("branding all-null", () => {
  it("falls back to the bare card with no name, logo, or scrim", async () => {
    getBrandingMock.mockResolvedValue({
      dojo_name: null,
      logo_url: null,
      background_image_url: null,
      primary_colour: "#1D4ED8",
    })

    renderLoginPage()

    await waitFor(() => {
      expect(getBrandingMock).toHaveBeenCalled()
    })

    expect(screen.getByText("Sign in")).toBeInTheDocument()
    expect(screen.queryByAltText("Dojo logo")).not.toBeInTheDocument()
    expect(document.querySelector(".bg-black\\/40")).toBeNull()
  })
})

describe("branding fetch fails", () => {
  it("tolerates the rejection silently and renders the bare card", async () => {
    getBrandingMock.mockRejectedValue(new Error("network error"))

    renderLoginPage()

    await waitFor(() => {
      expect(getBrandingMock).toHaveBeenCalled()
    })

    expect(screen.getByText("Sign in")).toBeInTheDocument()
    expect(screen.queryByAltText("Dojo logo")).not.toBeInTheDocument()
    expect(document.querySelector(".bg-black\\/40")).toBeNull()
  })
})

describe("signing in from a phone (#612)", () => {
  it("tells a Member whose passkey is on their phone to use the phone option", async () => {
    getBrandingMock.mockRejectedValue(new Error("network error"))

    renderLoginPage()

    expect(
      await screen.findByText(/passkey is on your phone\?.*phone or tablet.*scan the QR code/i),
    ).toBeInTheDocument()
  })

  it("offers a passkey for this device after a cross-platform sign-in", async () => {
    getBrandingMock.mockRejectedValue(new Error("network error"))
    vi.mocked(performPasskeyLogin).mockResolvedValue({
      detail: "ok",
      authenticatorAttachment: "cross-platform",
    })
    vi.stubGlobal("location", { ...window.location, assign: vi.fn() })
    Object.defineProperty(navigator, "credentials", { value: {}, configurable: true })
    sessionStorage.clear()

    renderLoginPage()
    await userEvent.type(screen.getByLabelText("Email"), "a@dojo.test")
    await userEvent.click(screen.getByRole("button", { name: "Sign in with passkey" }))

    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith("/"))
    expect(isDevicePasskeyOffered()).toBe(true)
    vi.unstubAllGlobals()
  })
})
