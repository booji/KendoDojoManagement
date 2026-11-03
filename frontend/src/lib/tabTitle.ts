// The browser tab shows the dojo name, or this when there is none (#555).
// index.html carries the same fallback for before the app loads.
const FALLBACK = "Kendo Dojo Management"

export const setTabTitle = (name: string | null) => {
  document.title = name || FALLBACK
}
