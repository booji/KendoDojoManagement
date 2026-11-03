// The Calendar Feed URL ends in the dojo name, because Thunderbird and GNOME
// Calendar name a subscription after the URL's last segment. Same rule as
// feed_url_name in backend/app/sessions/ical.py: the server answers only the
// current name, so the two must agree.
export const calendarFeedUrl = (origin: string, dojoName: string) => {
  const name = (dojoName.trim() || "Kendo Dojo Management").replaceAll("/", "-")
  return `${origin}/api/sessions/ical/${encodeURIComponent(name)}`
}
