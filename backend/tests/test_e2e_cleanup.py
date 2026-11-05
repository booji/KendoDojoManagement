"""The e2e harness removes the Members and Accounts a test created (#568).

e2e tests sign in and onboard through the live server, which commits for real,
so nothing rolls their rows back. ``leaves_members_as_found`` removes them,
and conftest wraps every e2e test and module in it.
"""

import requests

from tests.e2e_support import (
    API_URL,
    complete_onboarding,
    leaves_members_as_found,
    make_token,
)


def _member_of(token: str) -> requests.Response:
    return requests.get(
        f"{API_URL}/accounts/me/member", cookies={"access_token": token}, timeout=5
    )


def test_a_signed_in_and_onboarded_user_is_removed_afterwards() -> None:
    with leaves_members_as_found():
        token = make_token("member")
        complete_onboarding(token)
        assert _member_of(token).status_code == 200

    assert _member_of(token).status_code == 401
