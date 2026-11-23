// After a sign-in with a passkey from another device — a phone over QR, or a
// security key — offer to add one on this device (#612). The offer crosses the
// full page load that follows login in sessionStorage; a dismissal is kept in
// localStorage so this device never asks again.
const OFFER_KEY = "device_passkey_offer"
const DISMISSED_KEY = "device_passkey_offer_dismissed"

export const noteSignInAttachment = (attachment: AuthenticatorAttachment | null): void => {
  if (attachment === "cross-platform") sessionStorage.setItem(OFFER_KEY, "1")
  else sessionStorage.removeItem(OFFER_KEY)
}

export const isDevicePasskeyOffered = (): boolean =>
  sessionStorage.getItem(OFFER_KEY) !== null && localStorage.getItem(DISMISSED_KEY) === null

// The offer is shown once per sign-in, whatever the Member chooses.
export const closeDevicePasskeyOffer = (): void => {
  sessionStorage.removeItem(OFFER_KEY)
}

export const dismissDevicePasskeyOffer = (): void => {
  closeDevicePasskeyOffer()
  localStorage.setItem(DISMISSED_KEY, "1")
}
