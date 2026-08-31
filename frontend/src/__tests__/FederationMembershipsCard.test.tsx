/**
 * Unit tests for the Federation Membership card.
 *
 * The card used to exist twice — once on the Member detail page, once on the
 * user's own settings page — and could only be exercised by rendering a whole
 * page and stubbing `fetch`. It now takes a `FederationMembershipStore`, so
 * these tests drive it through that seam with an in-memory fake instead: no
 * fetch stubbing, and the same test covers both views because both views are
 * the same module.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import FederationMembershipsCard from "@/components/FederationMembershipsCard"
import type {
  FederationMembershipStore,
  FederationResponse,
  MemberFederationResponse,
} from "@/api/federations"
import * as federations from "@/api/federations"

const federation = (
  id: string,
  name: string,
  overrides: Partial<FederationResponse> = {},
): FederationResponse => ({
  id,
  name,
  abbreviation: null,
  iso_code: null,
  website: null,
  continental_grouping: null,
  type: null,
  is_pinned: false,
  is_active: true,
  ...overrides,
})

/** An in-memory FederationMembershipStore — the fake the seam exists for. */
const fakeStore = (
  initial: MemberFederationResponse[] = [],
): FederationMembershipStore & { rows: MemberFederationResponse[] } => {
  const rows = [...initial]
  let nextId = initial.length + 1
  return {
    rows,
    list: () => Promise.resolve([...rows]),
    add: (body) => {
      const created: MemberFederationResponse = {
        id: `mf-${nextId++}`,
        member_id: "member-1",
        federation_id: body.federation_id,
        member_number: body.member_number,
        renewal_date: body.renewal_date ?? null,
        renewal_status: null,
      }
      rows.push(created)
      return Promise.resolve(created)
    },
    update: (mfId, body) => {
      const row = rows.find((r) => r.id === mfId)
      if (row === undefined) return Promise.reject(new Error("not found"))
      if (body.member_number !== undefined) row.member_number = body.member_number
      if (body.renewal_date !== undefined) row.renewal_date = body.renewal_date
      return Promise.resolve({ ...row })
    },
    remove: (mfId) => {
      rows.splice(
        rows.findIndex((r) => r.id === mfId),
        1,
      )
      return Promise.resolve()
    },
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

const withCatalogue = (rows: FederationResponse[]): void => {
  vi.spyOn(federations, "listFederations").mockResolvedValue(rows)
}

describe("FederationMembershipsCard", () => {
  it("adds a membership through the store and lists it", async () => {
    const user = userEvent.setup()
    const store = fakeStore()
    withCatalogue([federation("fed-1", "British Kendo Association", { abbreviation: "BKA" })])

    render(<FederationMembershipsCard store={store} />)

    await screen.findByText("No federation memberships yet.")

    await user.click(screen.getByRole("button", { name: /add federation membership/i }))
    await user.type(screen.getByLabelText("Federation"), "British")
    await user.click(await screen.findByRole("button", { name: /British Kendo Association/ }))
    await user.type(screen.getByLabelText("Member number"), "BKA-12345")
    await user.click(screen.getByRole("button", { name: "Save" }))

    await waitFor(() => {
      expect(screen.getByText("British Kendo Association")).toBeInTheDocument()
    })
    expect(screen.getByText(/BKA-12345/)).toBeInTheDocument()
    expect(store.rows).toHaveLength(1)
  })

  it("removes a membership through the store", async () => {
    const user = userEvent.setup()
    const store = fakeStore([
      {
        id: "mf-1",
        member_id: "member-1",
        federation_id: "fed-1",
        member_number: "BKA-12345",
        renewal_date: null,
        renewal_status: null,
      },
    ])
    withCatalogue([federation("fed-1", "British Kendo Association")])

    render(<FederationMembershipsCard store={store} />)

    await user.click(await screen.findByRole("button", { name: /remove .* membership/i }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Remove" }))

    await waitFor(() => {
      expect(store.rows).toHaveLength(0)
    })
    expect(await screen.findByText("No federation memberships yet.")).toBeInTheDocument()
  })

  it("offers only active federations when adding", async () => {
    const user = userEvent.setup()
    withCatalogue([
      federation("fed-1", "British Kendo Association"),
      federation("fed-2", "Defunct Kendo Union", { is_active: false }),
    ])

    render(<FederationMembershipsCard store={fakeStore()} />)

    await user.click(await screen.findByRole("button", { name: /add federation membership/i }))
    await user.type(screen.getByLabelText("Federation"), "Kendo")

    expect(await screen.findByRole("button", { name: /British Kendo Association/ })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Defunct Kendo Union/ })).not.toBeInTheDocument()
  })

  it("surfaces a failed load", async () => {
    const store = fakeStore()
    store.list = () => Promise.reject({ status: 403, message: "Not authorized" })
    withCatalogue([])

    render(<FederationMembershipsCard store={store} />)

    expect(await screen.findByRole("alert")).toHaveTextContent("Not authorized")
  })
})
