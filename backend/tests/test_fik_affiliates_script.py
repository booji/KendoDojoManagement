"""The maintainer script that refreshes the bundled FIK affiliate list (#613).

Parsed against a trimmed, redacted copy of
https://www.kendo-fik.org/organization/affiliate saved in tests/fixtures: the
live page is fetched only when a maintainer runs the script.
"""

from pathlib import Path

import pytest

from app.federations.fik_catalogue import validate
from scripts.update_fik_affiliates import LayoutError, parse_affiliates

_PAGE = (Path(__file__).parent / "fixtures" / "fik_affiliate_page.html").read_text(
    encoding="utf-8"
)


def _by_key(records: list[dict]) -> dict[str, dict]:
    return {r["source_key"]: r for r in records}


def test_parses_every_entry_on_the_saved_page() -> None:
    records = parse_affiliates(_PAGE)

    assert len(records) == 13
    assert _by_key(records)["HU"]["name"] == "Hungarian Kendo, Iaido & Jodo Federation"
    assert _by_key(records)["ZA"] == {
        "source_key": "ZA",
        "name": "South African Kendo Federation",
        "iso_code": "ZA",
        "continental_grouping": "Africa",
        "website": "https://www.sakf.co.za",
        "type": "National",
    }


def test_parsed_records_pass_the_schema_check() -> None:
    validate(parse_affiliates(_PAGE))


def test_hawaii_is_a_us_subdivision_and_its_bare_url_gets_https() -> None:
    hawaii = _by_key(parse_affiliates(_PAGE))["US-HI"]

    assert hawaii["name"] == "Hawaii Kendo Federation"
    assert hawaii["continental_grouping"] == "Pan-Am"
    assert hawaii["website"] == "https://www.hawaiikendofederation.org"


def test_special_status_affiliates() -> None:
    records = _by_key(parse_affiliates(_PAGE))

    assert records["AW"]["type"] == "Special Status"
    assert records["MO"]["type"] == "Special Status"
    assert records["MO"]["continental_grouping"] == "Asia"


def test_continental_and_international_bodies_have_no_iso_code() -> None:
    records = _by_key(parse_affiliates(_PAGE))

    assert records["fik"] == {
        "source_key": "fik",
        "name": "International Kendo Federation",
        "iso_code": None,
        "continental_grouping": "Global",
        "website": "https://www.kendo-fik.org",
        "type": "Global Body",
    }
    assert records["ekf"]["name"] == "European Kendo Federation"
    assert records["ekf"]["type"] == "Regional Body"
    assert records["ekf"]["website"] == "https://www.ekf-eu.com"
    assert records["lakc"]["name"] == "Latin American Kendo Confederation"
    assert records["lakc"]["continental_grouping"] == "Pan-Am"


def test_homepage_variants() -> None:
    records = _by_key(parse_affiliates(_PAGE))

    assert records["CO"]["website"] == "https://kendocolombia.org/"  # plain text
    assert records["HU"]["website"] == "https://www.kendo.hu"  # first of three
    assert records["CN"]["website"] is None  # no Homepage field at all


def test_no_officials_are_kept() -> None:
    text = repr(parse_affiliates(_PAGE))

    assert "REDACTED" not in text
    assert "President" not in text


def test_unknown_country_heading_fails_loudly() -> None:
    page = _PAGE.replace(">GREAT BRITAIN</h5>", ">ATLANTIS</h5>")

    with pytest.raises(LayoutError, match="ATLANTIS"):
        parse_affiliates(page)


def test_a_page_without_the_list_fails_loudly() -> None:
    with pytest.raises(LayoutError):
        parse_affiliates("<html><body>Maintenance</body></html>")


def test_an_entry_without_a_name_fails_loudly() -> None:
    page = _PAGE.replace(
        "<dt>Name of the organization:</dt>\n<dd>Hungarian Kendo, Iaido &amp; Jodo Federation</dd>",
        "",
        1,
    )
    assert page != _PAGE

    with pytest.raises(LayoutError, match="HUNGARY"):
        parse_affiliates(page)
