# Coding standards

Read at review time, and before writing UI.

## UI Conventions

### Desktop Layout
Pages use full-width layout with `px-4` padding. No `max-w-*` constraint on page wrappers — content fills the available space beside the sidebar. Use responsive grid (`md:grid-cols-2`, `md:grid-cols-4` etc.) to structure content on wider screens rather than capping width.

### Copy to Clipboard
Clipboard copying goes through `frontend/src/components/CopyButton.tsx` — do
not hand-roll `navigator.clipboard.writeText` with its own `copied` state. Four
pages predate the component and still do (issue #367); if you are editing one
of them anyway, migrate it.

### Button Ordering (macOS HIG)
Action buttons are right-aligned (`justify-end`). Order left-to-right: most destructive → least destructive → primary/safe action. Example: `Cancel Series` | `Cancel Session` | `Edit`. The default/safe action always sits rightmost.

**Confirm dialogs are the exception.** A dialog that confirms an action the user just chose puts `Cancel` leftmost and the confirming action rightmost, even when that action is destructive: `Cancel` | `Delete permanently`. This is the HIG alert rule (Cancel on the leading side, the action on the trailing side); on small screens `DialogFooter` stacks them with Cancel at the bottom. For a destructive confirm, give Cancel the initial focus (`DialogContent initialFocus={cancelRef}`) so Enter on open never confirms. This follows the WAI-ARIA APG (focus the least destructive action) rather than the HIG's "no default button", which has no web equivalent short of focusing nothing. The exception: a dialog with an input, such as type-to-confirm, lets the input take focus instead. A destructive option that is *not* the dialog's main action still goes leftmost: `Discard` | `Cancel` | `Save`.
