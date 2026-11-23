"""login_show_logo defaults to true from b8c9d0e1f2a4 (#615).

A new row gets the default; a row saved before the revision keeps its value.
"""

import uuid

from tests.migration_support import sql, upgrade

_BEFORE = "a7b8c9d0e1f3"
_AFTER = "b8c9d0e1f2a4"


def settings_row() -> str:
    return f"""INSERT INTO dojo_settings (id, dojo_name, primary_colour,
        checkin_window_before_minutes, checkin_window_after_minutes, updated_at)
        VALUES ('{uuid.uuid4()}', 'Dojo', '#000000', 60, 120, now())"""


async def test_new_row_shows_logo_by_default(scratch_db):
    await upgrade(scratch_db, _AFTER)
    await sql(scratch_db, settings_row())

    rows = await sql(scratch_db, "SELECT login_show_logo FROM dojo_settings")

    assert rows == [(True,)]


async def test_upgrade_leaves_an_existing_row_untouched(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await sql(scratch_db, settings_row())

    await upgrade(scratch_db, _AFTER)

    rows = await sql(scratch_db, "SELECT login_show_logo FROM dojo_settings")
    assert rows == [(False,)]
