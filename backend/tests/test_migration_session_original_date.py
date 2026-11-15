"""A Session moved before a7b8c9d0e1f3 is backfilled as edited (#578).

The migration records each generated Session's slot as its current date, the
best record left. A Session an Admin had moved off the recurrence would then
cover a slot the recurrence does not, and the next reconcile would delete it.
Marking it edited keeps it.
"""

import uuid

from tests.migration_support import sql, upgrade

_BEFORE = "e3f4a5b6c7d9"
_AFTER = "a7b8c9d0e1f3"


def instance(session_id: str, day: str, template_id: str | None) -> str:
    template_sql = f"'{template_id}'" if template_id else "NULL"
    return f"""INSERT INTO session_instances (id, title, date, template_id, cancelled)
        VALUES ('{session_id}', 'Keiko', '{day}', {template_sql}, false)"""


async def test_upgrade_marks_sessions_off_the_recurrence_edited(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    template = str(uuid.uuid4())
    on_slot, moved_day, moved_week, adhoc = (str(uuid.uuid4()) for _ in range(4))
    await sql(
        scratch_db,
        # Every other Monday from Monday 2 November.
        f"""INSERT INTO session_templates (id, title, start_date, end_date,
            recurrence, recurrence_days, interval_weeks, is_active)
            VALUES ('{template}', 'Keiko', '2026-11-02', '2026-11-30', 'weekly',
                    '[0]', 2, true)""",
        instance(on_slot, "2026-11-16", template),
        instance(moved_day, "2026-11-03", template),  # a Tuesday
        instance(moved_week, "2026-11-09", template),  # the off-week Monday
        instance(adhoc, "2026-11-10", None),
    )

    await upgrade(scratch_db, _AFTER)

    rows = await sql(scratch_db, "SELECT id, edited FROM session_instances")
    assert {str(session_id): edited for session_id, edited in rows} == {
        on_slot: False,
        moved_day: True,
        moved_week: True,
        adhoc: False,
    }
