// Whether this device has seen the guided tour (#609). Per device by design:
// a new device shows it again. Kept apart from tour.ts so checking it does not
// load driver.js.
const SEEN_KEY = "tour_seen"

export const isTourSeen = (): boolean => localStorage.getItem(SEEN_KEY) !== null

export const markTourSeen = (): void => localStorage.setItem(SEEN_KEY, "1")

// Settings → "Take the tour": the Dashboard then starts it again.
export const resetTour = (): void => localStorage.removeItem(SEEN_KEY)
