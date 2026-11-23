"""Every update body refuses null where its column does (#585).

`PartialUpdate.not_null` restates what the ORM already knows about the
columns, so nothing else checks the two agree. A NOT NULL column missing from
`not_null` turns a null into a database error, a 500, which is how
`dojo_name: null` failed before (C18). The other direction is allowed:
`not_null` may be stricter than the column, as Member email is (nullable only
for GDPR erasure) and a template's recurrence_days.
"""

from __future__ import annotations

import pytest

from app.core.partial_update import PartialUpdate
from app.federations.db_models import Federation
from app.federations.schemas import FederationUpdate
from app.member_federations.db_models import MemberFederation
from app.member_federations.schemas import MemberFederationUpdate
from app.members.db_models import Member
from app.members.models import SelfUpdateMemberRequest, UpdateMemberRequest
from app.sessions.db_models import SessionInstance, SessionTemplate
from app.sessions.models import SessionInstanceUpdate, SessionTemplateUpdate
from app.settings.models import DojoSettings
from app.settings.router import DojoSettingsUpdate


@pytest.mark.parametrize(
    ("body", "table"),
    [
        (SessionInstanceUpdate, SessionInstance),
        (SessionTemplateUpdate, SessionTemplate),
        (FederationUpdate, Federation),
        (MemberFederationUpdate, MemberFederation),
        (UpdateMemberRequest, Member),
        (SelfUpdateMemberRequest, Member),
        (DojoSettingsUpdate, DojoSettings),
    ],
)
def test_not_null_covers_every_not_null_column(
    body: type[PartialUpdate], table: type
) -> None:
    columns = table.__table__.c
    required = {
        name
        for name in body.model_fields
        if name in columns and not columns[name].nullable
    }
    assert required <= body.not_null, required - body.not_null
