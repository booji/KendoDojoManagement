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


def test_their_grades_attendance_and_recovery_tokens_go_too() -> None:
    with leaves_members_as_found():
        admin = make_token("admin")
        member = make_token("member")
        member_id = complete_onboarding(member)["id"]

        def post(path: str, token: str = admin, **body: object) -> dict:
            r = requests.post(
                f"{API_URL}{path}", json=body, cookies={"access_token": token}
            )
            r.raise_for_status()
            return r.json()

        type_id = requests.get(
            f"{API_URL}/session-types", cookies={"access_token": admin}
        ).json()[0]["id"]
        session = post(
            "/sessions",
            title="Cleanup Test Session",
            date="2299-06-01",
            segments=[
                {"start_time": "18:00", "duration_minutes": 60, "type_ids": [type_id]}
            ],
        )
        post(f"/sessions/{session['id']}/attendance", member_id=member_id)
        post(f"/members/{member_id}/grades", grade="GOKYUU")
        post("/auth/recovery/codes/generate", token=member)
        # Issued by one new Account for another: both are removed.
        post("/auth/recovery/admin-token", member_id=member_id)

    assert _member_of(member).status_code == 401
    assert _member_of(admin).status_code == 401


# The next two run in file order: conftest's wrapper removes what the first
# left behind before the second starts.
_left_behind: list[str] = []


def test_an_e2e_test_that_leaves_a_user_behind() -> None:
    token = make_token("member")
    complete_onboarding(token)
    _left_behind.append(token)


def test_finds_it_gone_by_the_next_test() -> None:
    assert _left_behind, "runs after test_an_e2e_test_that_leaves_a_user_behind"
    assert _member_of(_left_behind[0]).status_code == 401
