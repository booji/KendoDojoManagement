/**
 * The Calendar Feed URL ends in the dojo name: Thunderbird and GNOME Calendar
 * name a subscription after the URL's last segment. The server answers only
 * the current name (feed_url_name in backend/app/sessions/ical.py).
 */

import { describe, it, expect } from "vitest"

import { calendarFeedUrl } from "@/lib/calendarFeed"

describe("calendarFeedUrl", () => {
  it.each([
    ["Shoshinkai Reading", "Shoshinkai%20Reading"],
    ["Kendo Club A/B", "Kendo%20Club%20A-B"],
    ["  Shoshinkai  ", "Shoshinkai"],
    ["   ", "Kendo%20Dojo%20Management"],
    ["剣道 #1?", "%E5%89%A3%E9%81%93%20%231%3F"],
  ])("ends %j in %s", (dojoName, segment) => {
    expect(calendarFeedUrl("https://dojo.example", dojoName)).toBe(
      `https://dojo.example/api/sessions/ical/${segment}`,
    )
  })
})
