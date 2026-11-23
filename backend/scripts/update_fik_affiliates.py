"""Refresh app/federations/fik_affiliates.json from the FIK's affiliate page.

Maintainer tool, run before tagging a release candidate
(docs/contributing/releasing.md), from backend/:

    uv run python -m scripts.update_fik_affiliates

Fetches https://www.kendo-fik.org/organization/affiliate, parses it and
rewrites the JSON; review the diff in a PR. If the page's layout has changed
it raises LayoutError and writes nothing, rather than a partial list.
Officials are personal data and are never read into the output.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from typing import Any

from app.federations.fik_catalogue import CATALOGUE_PATH, validate

URL = "https://www.kendo-fik.org/organization/affiliate"

# The page's continent headings, as the Admin Settings groupings name them.
_GROUPINGS = {
    "AFRICA": "Africa",
    "AMERICA": "Pan-Am",
    "ASIA": "Asia",
    "OCEANIA": "Oceania",
    "EUROPE": "Europe",
}

# Country headings to ISO 3166 codes. A heading missing here fails the run:
# add it after checking the code.
_ISO = {
    "SOUTH AFRICA": "ZA",
    "TUNISIA": "TN",
    "UNITED STATES OF AMERICA": "US",
    "HAWAII": "US-HI",
    "CANADA": "CA",
    "MEXICO": "MX",
    "BRAZIL": "BR",
    "ARGENTINA": "AR",
    "VENEZUELA": "VE",
    "ARUBA": "AW",
    "CHILE": "CL",
    "DOMINICAN REPUBLIC": "DO",
    "ECUADOR": "EC",
    "COLOMBIA": "CO",
    "PERU": "PE",
    "URUGUAY": "UY",
    "JAPAN": "JP",
    "KOREA": "KR",
    "CHINESE TAIPEI": "TW",
    "HONG KONG, CHINA": "HK",
    "MALAYSIA": "MY",
    "SINGAPORE": "SG",
    "THAILAND": "TH",
    "MACAO, CHINA": "MO",
    "CHINA": "CN",
    "INDONESIA": "ID",
    "MONGOLIA": "MN",
    "PHILIPPINES": "PH",
    "AUSTRALIA": "AU",
    "NEW ZEALAND": "NZ",
    "GREAT BRITAIN": "GB",
    "FRANCE": "FR",
    "SWEDEN": "SE",
    "BELGIUM": "BE",
    "NETHERLANDS": "NL",
    "SWITZERLAND": "CH",
    "GERMANY": "DE",
    "SPAIN": "ES",
    "AUSTRIA": "AT",
    "NORWAY": "NO",
    "DENMARK": "DK",
    "FINLAND": "FI",
    "ITALY": "IT",
    "HUNGARY": "HU",
    "POLAND": "PL",
    "SERBIA": "RS",
    "CZECH REPUBLIC": "CZ",
    "ROMANIA": "RO",
    "LUXEMBOURG": "LU",
    "RUSSIAN FEDERATION": "RU",
    "PORTUGAL": "PT",
    "IRELAND": "IE",
    "BULGARIA": "BG",
    "GREECE": "GR",
    "ISRAEL": "IL",
    "MONTENEGRO": "ME",
    "LATVIA": "LV",
    "LITHUANIA": "LT",
    "CROATIA": "HR",
    "SLOVENIA": "SI",
    "TURKEY": "TR",
    "MALTA": "MT",
    "NORTH MACEDONIA": "MK",
    "UKRAINE": "UA",
}

# Bodies that are not a country: (source_key, name, type, grouping or None to
# take the continent heading). FIK and EKF entries carry no name field.
_BODIES = {
    "INTERNATIONAL KENDO FEDERATION (FIK)": (
        "fik",
        "International Kendo Federation",
        "Global Body",
        "Global",
    ),
    "EUROPEAN KENDO FEDERATION (EKF)": (
        "ekf",
        "European Kendo Federation",
        "Regional Body",
        None,
    ),
    "LAKC (LATIN AMERICAN KENDO CONFEDERATION)": (
        "lakc",
        "Latin American Kendo Confederation",
        "Regional Body",
        None,
    ),
}

# The page spells it "spacial" for Aruba.
_SPECIAL = re.compile(r"\s*\(affiliated under sp[ae]cial status\)\s*$", re.I)


_HEADINGS = {("h4", "orga-ListArea_Area"), ("h5", "orga-ListArea_Heading")}


class LayoutError(RuntimeError):
    """The page no longer has the layout this parser knows."""


class _Collector(HTMLParser):
    """Flattens the list into (continent, heading, [(label, value)]) entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str, list[tuple[str, str]]]] = []
        self._tag: str | None = None
        self._text = ""
        self._continent: str | None = None
        self._label: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class") or ""
        if (tag, cls) in _HEADINGS:
            self._tag, self._text = tag, ""
        elif tag in ("dt", "dd") and self.entries:
            self._tag, self._text = tag, ""

    def handle_data(self, data: str) -> None:
        if self._tag:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag != self._tag:
            return
        text = " ".join(self._text.split())
        self._tag = None
        if tag == "h4":
            self._continent = text
        elif tag == "h5":
            if self._continent is None:
                raise LayoutError(f"Entry {text!r} is not under a continent heading")
            self.entries.append((self._continent, text, []))
        elif tag == "dt":
            self._label = text.rstrip(":").strip().lower()
        elif self._label is not None:
            self.entries[-1][2].append((self._label, text))
            self._label = None


def _website(value: str | None) -> str | None:
    """The first homepage, as https; None for N/A or none."""
    if value is None or value.upper() in ("", "N/A"):
        return None
    first = re.split(r"[,\s]+", value.strip())[0]
    return "https://" + re.sub(r"^https?://", "", first, flags=re.I)


def parse_affiliates(html: str) -> list[dict[str, Any]]:
    """The affiliate records on the FIK page. Raises LayoutError on anything
    this parser does not recognise; the result passes the schema check."""
    collector = _Collector()
    collector.feed(html)
    collector.close()
    if not collector.entries:
        raise LayoutError("No affiliate entries found: the page layout changed")
    records = []
    for continent, heading, fields in collector.entries:
        grouping = _GROUPINGS.get(continent)
        if grouping is None:
            raise LayoutError(f"Unknown continent heading {continent!r}")
        values: dict[str, str] = {}
        for label, value in fields:
            # Labels vary in case and spelling ("organziation").
            if label.startswith("name of the org"):
                values["name"] = value
            elif label == "homepage":
                values["homepage"] = value
        body = _BODIES.get(heading.upper())
        special = _SPECIAL.search(heading)
        if body:
            key, name, type_, fixed_grouping = body
            iso = None
            grouping = fixed_grouping or grouping
        else:
            country = _SPECIAL.sub("", heading).upper()
            iso = _ISO.get(country)
            if iso is None:
                raise LayoutError(f"Unknown country {heading!r}: add it to _ISO")
            name = values.get("name")
            if not name:
                raise LayoutError(f"Entry {heading!r} has no organisation name")
            key, type_ = iso, "Special Status" if special else "National"
        records.append(
            {
                "source_key": key,
                "name": name,
                "iso_code": iso,
                "continental_grouping": grouping,
                "website": _website(values.get("homepage")),
                "type": type_,
            }
        )
    try:
        validate(records)
    except ValueError as exc:
        raise LayoutError(str(exc)) from exc
    return records


def main() -> None:
    request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    records = parse_affiliates(html)
    CATALOGUE_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(records)} affiliates to {CATALOGUE_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
