"""The Session Template lifecycle: create, generate, reschedule, extend, cancel.

A Session Template is a recurrence rule, and the instances it covers are
derived from it. Keeping those two in step is the whole job, and it used to be
done in the HTTP handlers: five endpoints in ``app/sessions/router.py`` each
drove the two repositories directly, sharing a private
``_apply_recurrence_delta`` between them. The rules — what a reschedule
preserves, how far ahead an extension may reach — were only reachable through
an ASGI request.

This module owns them instead. It takes the repositories as arguments, in the
style of ``passkey_service`` and ``invite_service``, and hands back records.
The router keeps what is genuinely HTTP: authentication, status codes, response
shaping, and ``uow.commit()`` at the request boundary.

Failures cross back as this codebase already expresses them:

- a missing template is ``None``, as the repositories report it;
- a broken rule is a ``ValueError`` carrying the message, the way
  ``SqlSessionTypeRepository.add`` reports a duplicate name.

so nothing here needs to know an HTTP status code to be tested.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
)
from app.sessions.service import (
    TEMPLATE_MAX_HORIZON_MONTHS,
    add_months,
    covered_dates,
    generate_instances,
)


async def _slots_for(
    template_id: str, instance_repo: AbstractSessionInstanceRepository
) -> dict[str, dict[str, Any]]:
    """The template's Sessions, keyed by the slot each covers: the date it was
    generated for, wherever it has since been moved (#578). A Session with no
    slot (ad-hoc, or a pre-#578 duplicate) covers none and is never
    reconciled."""
    return {
        record["original_date"]: record
        for record in await instance_repo.list()
        if record.get("template_id") == template_id and record.get("original_date")
    }


async def _active_template(
    template_id: str, template_repo: AbstractSessionTemplateRepository
) -> dict[str, Any] | None:
    """The template, None if missing. Raises ValueError if its series is
    cancelled: generating for it would bring back live Sessions the Admin
    cancelled (audit C6)."""
    template = await template_repo.get(template_id)
    if template is not None and not template["is_active"]:
        raise ValueError("a cancelled series cannot be changed")
    return template


async def _apply_recurrence_delta(
    template: dict[str, Any],
    template_id: str,
    instance_repo: AbstractSessionInstanceRepository,
) -> None:
    """Reconcile persisted instances with the template's recurrence.

    Adds instances for newly-covered dates and removes those for dates the
    recurrence no longer covers. Dates that remain covered are left completely
    untouched, so an individually edited or cancelled instance on a
    still-covered date is never overwritten or deleted (#258 AC3).

    Instances are matched to the recurrence by the slot they cover, so a moved
    one keeps its slot (#578). Only today onwards is reconciled: a past Session
    records training that happened, so it is never deleted, and the past is
    never backfilled with Sessions that did not take place. Nor is a Session
    an Admin has edited, or one with Attendance, ever deleted.

    Cancelling or reinstating a Session is not an edit (#579): a future,
    unattended Session that was only cancelled, or cancelled and reinstated,
    is deleted with a slot the recurrence no longer covers.
    """
    today = date.today().isoformat()
    existing = await _slots_for(template_id, instance_repo)
    wanted_slots = covered_dates(template)

    horizon = date.fromisoformat(template["end_date"])
    for data in generate_instances(template, horizon, set(existing)):
        if data["date"] >= today:
            await instance_repo.add(data)

    for slot, record in existing.items():
        if (
            slot not in wanted_slots
            and record["date"] >= today
            and not record["edited"]
        ):
            await instance_repo.delete_unattended(record["id"])


async def create(
    data: dict[str, Any],
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> dict[str, Any]:
    """Persist a template and the instances its recurrence covers."""
    template = await template_repo.add(data)
    horizon = date.fromisoformat(template["end_date"])
    for instance_data in generate_instances(template, horizon):
        await instance_repo.add(instance_data)
    return template


async def generate_to_horizon(
    template_id: str,
    horizon: date,
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> list[dict[str, Any]] | None:
    """Generate instances up to ``horizon``, skipping dates already covered.

    Returns the instances created — empty when the horizon adds none — or None
    if the template does not exist. Idempotent by construction: the dates
    already covered for this template are excluded, so repeating the call
    never produces a second instance for a date that already has one.
    Raises ValueError if the series is cancelled.
    """
    template = await _active_template(template_id, template_repo)
    if template is None:
        return None

    existing_slots = set(await _slots_for(template_id, instance_repo))
    return [
        await instance_repo.add(data)
        for data in generate_instances(template, horizon, existing_slots)
    ]


async def reschedule(
    template_id: str,
    data: dict[str, Any],
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> dict[str, Any] | None:
    """Apply changes to a template and reconcile its instances.

    Raises ValueError if the series is cancelled.
    """
    if await _active_template(template_id, template_repo) is None:
        return None
    template = await template_repo.update(template_id, data)
    if template is None:
        return None
    await _apply_recurrence_delta(template, template_id, instance_repo)
    return template


async def extend(
    template_id: str,
    new_end: date,
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> dict[str, Any] | None:
    """Move a template's end date later and generate the newly-covered dates.

    Raises ValueError if the series is cancelled, the new end date moves
    backwards, or it reaches beyond the horizon cap — a recurring template
    must stay bounded, and the cap applies from today rather than from the
    template's start, so repeated extensions cannot walk it indefinitely into
    the future.
    """
    template = await _active_template(template_id, template_repo)
    if template is None:
        return None

    current_end = date.fromisoformat(template["end_date"])
    if new_end < current_end:
        raise ValueError(
            "end_date must not be earlier than the template's current end_date"
        )
    if new_end > add_months(date.today(), TEMPLATE_MAX_HORIZON_MONTHS):
        raise ValueError(
            f"end_date must not be more than {TEMPLATE_MAX_HORIZON_MONTHS} "
            "months from today"
        )

    extended = await template_repo.update(
        template_id, {"end_date": new_end.isoformat()}
    )
    assert extended is not None  # read moments ago, in the same transaction
    await _apply_recurrence_delta(extended, template_id, instance_repo)
    return extended


async def cancel(
    template_id: str,
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> dict[str, Any] | None:
    """Deactivate a template and cancel its future instances.

    Past instances are left alone: they record training that happened, and
    cancelling the series does not unmake it.
    """
    template = await template_repo.deactivate(template_id)
    if template is None:
        return None
    await instance_repo.cancel_future_for_template(template_id, date.today())
    return template
