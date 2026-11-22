"""Browser (Playwright) test for #560: the Charts tab on /reports.

An Admin opens the Charts tab and sees the grade distribution. The Admin's
own Member is active and has no Promotion, so Mukyū always has a bar; other
tests share the database, so counts are not asserted here
(test_grade_distribution.py covers them). The autouse e2e cleanup in
conftest.py (#568) removes the Admin and their Member afterwards, so they do
not leak into other tests' counts.
"""

import uuid

import pytest
import requests
from playwright.sync_api import Page, Route, expect

from app.auth.models import AccountClaims
from tests.e2e_support import complete_onboarding, login_as

BASE_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"


@pytest.fixture
def admin_claims():
    return AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:6]}@dojo.test",
        role="admin",
    )


def test_admin_sees_the_grade_distribution_chart(
    page: Page, admin_claims: AccountClaims
) -> None:
    token = login_as(admin_claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")

    expect(page.get_by_role("checkbox", name="Active", exact=True)).to_be_checked()
    expect(page.get_by_role("heading", name="Grade distribution")).to_be_visible()
    expect(page.get_by_role("heading", name="Attendance Streaks")).to_be_visible()
    expect(
        page.get_by_role("heading", name="Attendance Rate", exact=True)
    ).to_be_visible()
    expect(page.locator(".recharts-bar-rectangle").first).to_be_visible()
    expect(
        page.locator("[data-slot=chart]").get_by_text("Mukyū", exact=True)
    ).to_be_visible()


def test_admin_sees_the_headcount_over_the_range(
    page: Page, admin_claims: AccountClaims
) -> None:
    # Other tests decide whether the range holds any Session, so this checks
    # the headcount loads (a chart or its empty state), not what it counts.
    token = login_as(admin_claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")
    charts = page.get_by_role("tabpanel", name="Charts")

    expect(charts.get_by_label("From")).not_to_have_value("")
    expect(charts.get_by_role("heading", name="Headcount per Session")).to_be_visible()
    expect(
        charts.get_by_role("table", name="Headcount per Session").or_(
            charts.get_by_text("No held Sessions in this range.")
        )
    ).to_be_attached()
    expect(charts.get_by_role("alert")).to_have_count(0)


def test_chart_bars_keep_their_colour_under_the_production_csp(
    page: Page, admin_claims: AccountClaims
) -> None:
    # Vite serves no CSP, so the page gets the backend's real header; without
    # it this test proves nothing (#607). An SVG fill whose var() is unset
    # falls back to black.
    #
    # The dev server's own inline preamble <script> and injected <style>s are
    # absent from the production build, so they are let through with a nonce
    # (Vite's client reads it from meta[property=csp-nonce]). Anything the app
    # itself injects carries no nonce, and is blocked as in production.
    nonce = uuid.uuid4().hex
    csp = (
        requests.get(f"{BACKEND_URL}/health").headers["Content-Security-Policy"]
        + f"; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'nonce-{nonce}'"
    )

    def with_csp(route: Route) -> None:
        response = route.fetch()
        html = response.text().replace("<script", f'<script nonce="{nonce}"')
        html = html.replace(
            "<head>", f'<head><meta property="csp-nonce" nonce="{nonce}">', 1
        )
        headers = {k: v for k, v in response.headers.items() if k != "content-length"}
        route.fulfill(
            response=response,
            body=html,
            headers={**headers, "content-security-policy": csp},
        )

    page.route(f"{BASE_URL}/reports", with_csp)
    page.add_init_script(
        """
        window.__cspViolations = [];
        document.addEventListener("securitypolicyviolation", (e) => {
          window.__cspViolations.push(
            `${e.effectiveDirective} ${e.sourceFile}:${e.lineNumber} ` +
              (e.target.outerHTML ?? "").slice(0, 120)
          );
        });
        """
    )
    token = login_as(admin_claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")

    bar = page.locator(".recharts-bar-rectangle path").first
    expect(bar).to_be_visible()
    fill = bar.evaluate("el => getComputedStyle(el).fill")
    assert fill not in ("rgb(0, 0, 0)", "none", ""), fill
    violations = page.evaluate("window.__cspViolations")
    assert violations == [], "\n".join(violations)
