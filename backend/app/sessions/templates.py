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


async def _instances_for(
    template_id: str, instance_repo: AbstractSessionInstanceRepository
) -> list[dict[str, Any]]:
    return [
        record
        for record in await instance_repo.list()
        if record.get("template_id") == template_id
    ]


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
    """
    existing_by_date = {
        record["date"]: record
        for record in await _instances_for(template_id, instance_repo)
    }
    wanted_dates = covered_dates(template)

    horizon = date.fromisoformat(template["end_date"])
    for data in generate_instances(template, horizon, set(existing_by_date)):
        await instance_repo.add(data)

    for iso_date, record in existing_by_date.items():
        if iso_date not in wanted_dates:
            await instance_repo.delete(record["id"])


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
    already persisted for this template are excluded, so repeating the call
    never produces a second instance on a date that already has one.
    """
    template = await template_repo.get(template_id)
    if template is None:
        return None

    existing_dates = {
        record["date"] for record in await _instances_for(template_id, instance_repo)
    }
    return [
        await instance_repo.add(data)
        for data in generate_instances(template, horizon, existing_dates)
    ]


async def reschedule(
    template_id: str,
    data: dict[str, Any],
    template_repo: AbstractSessionTemplateRepository,
    instance_repo: AbstractSessionInstanceRepository,
) -> dict[str, Any] | None:
    """Apply changes to a template and reconcile its instances."""
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

    Raises ValueError if the new end date moves backwards, or reaches beyond
    the horizon cap — a recurring template must stay bounded, and the cap
    applies from today rather than from the template's start, so repeated
    extensions cannot walk it indefinitely into the future.
    """
    template = await template_repo.get(template_id)
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
