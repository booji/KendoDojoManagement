import { useCallback, useEffect, useState } from "react"
import { useOutletContext } from "react-router-dom"
import { issueInvite, listInvites, revokeInvite } from "@/api/invites"
import type { InviteListItem, InviteMintResponse, InviteStatus } from "@/api/invites"
import { isApiError } from "@/api/auth"
import type { AccountClaims } from "@/api/auth"
import CopyButton from "@/components/CopyButton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader } from "@/components/ui/page-header"
import { EmptyState } from "@/components/ui/empty-state"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type LayoutContext = { user: AccountClaims }

const STATUS_LABEL: Record<InviteStatus, string> = {
  pending: "Pending",
  redeemed: "Redeemed",
  expired: "Expired",
  revoked: "Revoked",
}

const STATUS_VARIANT: Record<
  InviteStatus,
  "outline" | "success" | "secondary" | "destructive"
> = {
  pending: "outline",
  redeemed: "success",
  expired: "secondary",
  revoked: "destructive",
}

const formatDate = (iso: string): string => new Date(iso).toLocaleString()

// The full mint/list/revoke UI. Assumes the caller has already gated access to
// admins only — this component does no authorization checking of its own.
export const InviteManagementSection = () => {
  const [invites, setInvites] = useState<InviteListItem[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [email, setEmail] = useState("")
  const [firstName, setFirstName] = useState("")
  const [surname, setSurname] = useState("")
  const [issuing, setIssuing] = useState(false)
  const [issueError, setIssueError] = useState<string | null>(null)
  // The plaintext link is only ever held in local component state — never
  // persisted, never re-derived from the invite list (which never contains
  // it) — so a reload naturally makes it disappear for good.
  const [minted, setMinted] = useState<InviteMintResponse | null>(null)

  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<string | null>(null)

  const loadInvites = useCallback(() => {
    listInvites()
      .then((data) => setInvites(data))
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load invites")
      })
  }, [])

  useEffect(() => {
    loadInvites()
  }, [loadInvites])

  const handleIssue = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = email.trim()
    const trimmedFirstName = firstName.trim()
    const trimmedSurname = surname.trim()
    if (!trimmed || !trimmedFirstName || !trimmedSurname) return
    setIssuing(true)
    setIssueError(null)
    try {
      const result = await issueInvite(trimmed, trimmedFirstName, trimmedSurname)
      setMinted(result)
      setEmail("")
      setFirstName("")
      setSurname("")
      loadInvites()
    } catch (err) {
      setIssueError(isApiError(err) ? err.message : "Failed to issue invite")
    } finally {
      setIssuing(false)
    }
  }

  const handleRevoke = async (id: string) => {
    setRevokingId(id)
    setRevokeError(null)
    try {
      const updated = await revokeInvite(id)
      setInvites((prev) =>
        prev !== null
          ? prev.map((inv) => (inv.id === id ? { ...inv, status: updated.status } : inv))
          : prev
      )
    } catch (err) {
      setRevokeError(isApiError(err) ? err.message : "Failed to revoke invite")
    } finally {
      setRevokingId(null)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Issue an invite</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            onSubmit={(e) => void handleIssue(e)}
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
          >
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="invite-first-name-input">First name</Label>
              <Input
                id="invite-first-name-input"
                data-testid="invite-first-name-input"
                placeholder="Keiko"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                required
              />
            </div>
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="invite-surname-input">Surname</Label>
              <Input
                id="invite-surname-input"
                data-testid="invite-surname-input"
                placeholder="Tanaka"
                value={surname}
                onChange={(e) => setSurname(e.target.value)}
                required
              />
            </div>
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="invite-email-input">Email</Label>
              <Input
                id="invite-email-input"
                data-testid="invite-email-input"
                type="email"
                placeholder="newmember@dojo.test"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <Button
              type="submit"
              data-testid="invite-submit"
              disabled={
                issuing ||
                email.trim() === "" ||
                firstName.trim() === "" ||
                surname.trim() === ""
              }
              className="min-h-[44px] shrink-0"
            >
              {issuing ? "Issuing…" : "Issue invite"}
            </Button>
          </form>
          {issueError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {issueError}
            </p>
          )}

          {minted !== null && (
            <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-700 dark:bg-amber-950">
              <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                Invite created for {minted.email}. Copy this link now — it will not be
                shown again.
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <code
                  data-testid="invite-link"
                  className="flex-1 min-w-0 truncate rounded-md bg-background border border-border px-3 py-2 font-mono text-sm"
                >
                  {minted.link}
                </code>
                <CopyButton value={minted.link} label="Copy invite link" />
              </div>
              <p className="text-xs text-amber-800 dark:text-amber-300">
                Expires {formatDate(minted.expires_at)}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Invites</CardTitle>
        </CardHeader>
        <CardContent>
          {revokeError !== null && (
            <p className="text-sm text-destructive mb-3" role="alert">
              {revokeError}
            </p>
          )}
          {invites === null && loadError === null && (
            <div className="space-y-2">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          )}
          {loadError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {loadError}
            </p>
          )}
          {invites !== null && invites.length === 0 && (
            <EmptyState message="No invites issued yet." />
          )}
          {invites !== null && invites.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead className="w-24" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((inv) => (
                    <TableRow key={inv.id} data-testid="invite-row">
                      <TableCell className="font-medium">
                        {inv.first_name} {inv.surname}
                      </TableCell>
                      <TableCell>{inv.email}</TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_VARIANT[inv.status]}
                          data-testid={`invite-status-${inv.status}`}
                        >
                          {STATUS_LABEL[inv.status]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(inv.expires_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {inv.status === "pending" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            data-testid="invite-revoke-button"
                            disabled={revokingId === inv.id}
                            onClick={() => void handleRevoke(inv.id)}
                          >
                            {revokingId === inv.id ? "Revoking…" : "Revoke"}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// Standalone page at /settings/invites. Non-admins get a forbidden state
// rather than the issuance form — checked here rather than relying solely on
// route-level gating so the page itself is safe to link to directly.
const AdminInvitesPage = () => {
  const { user } = useOutletContext<LayoutContext>()

  if (user.role !== "admin") {
    return (
      <div className="px-4 py-6">
        <p data-testid="forbidden" role="alert" className="text-sm text-destructive">
          You don&apos;t have permission to view this page.
        </p>
      </div>
    )
  }

  return (
    <div className="px-4 py-6 space-y-6">
      <PageHeader title="Invites" />
      <InviteManagementSection />
    </div>
  )
}

export default AdminInvitesPage
