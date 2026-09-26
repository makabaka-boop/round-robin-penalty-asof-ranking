import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


def _row_teams(page):
    return page.locator('[data-testid="standings-table"] tbody tr td:nth-child(2)').all_inner_texts()


def _round_teams(page):
    return page.locator(
        '[data-testid="round-standings-table"] tbody tr td:nth-child(2)'
    ).all_inner_texts()


def _round_row(page, team):
    rows = page.locator('[data-testid="round-standings-table"] tbody tr')
    for row in rows.all():
        cells = row.locator("td").all_inner_texts()
        if cells[1] == team:
            return cells
    raise AssertionError(f"no standings row for team {team}")


def _launch_browser():
    manager = sync_playwright().start()
    try:
        browser = manager.chromium.launch(headless=True)
    except Exception as exc:  # Browser binary is unavailable in lightweight CI.
        manager.stop()
        pytest.skip(f"Chromium is not available: {exc}")
    return manager, browser


def test_edit_score_replaces_explanation_with_current_version(base_url):
    manager, browser = _launch_browser()
    page = browser.new_page()
    try:
        page.goto(base_url, wait_until="networkidle")

        # Seed: A>B, C>A, A>D, B>C, B>D, C>D. A/B/C form a 3-point cycle
        # with identical global stats, so the group falls through to global
        # tiebreakers and finally ASCII order.
        page.get_by_role("button", name="计算名次").click()
        expect(page.locator('[data-testid="result-version"]')).to_have_text("当前请求版本：1")
        expect(page.locator('[data-testid="standings-table"] tbody tr')).to_have_count(4)
        assert _row_teams(page) == ["A", "B", "C", "D"]
        expect(page.locator('[data-testid="trace-card"]')).to_contain_text("全局净胜球")

        # Change B-C from 1:0 to 0:1 (fourth pair, B vs C). Editing must
        # immediately retire the version-1 result and its explanation.
        bc_row = page.locator(".match-row").nth(3)
        bc_row.locator(".score").nth(0).fill("0")
        bc_row.locator(".score").nth(1).fill("1")
        expect(page.locator('[data-testid="standings-card"]')).to_have_count(0)
        expect(page.locator('[data-testid="trace-card"]')).to_have_count(0)

        page.get_by_role("button", name="计算名次").click()
        expect(page.locator('[data-testid="result-version"]')).to_have_text("当前请求版本：2")
        # C now wins every game; only the fresh version-2 explanation is shown.
        assert _row_teams(page) == ["C", "A", "B", "D"]
        expect(page.locator('[data-testid="trace-card"]')).to_have_count(0)
        expect(page.locator('[data-testid="result-version"]')).to_have_text("当前请求版本：2")
    finally:
        browser.close()
        manager.stop()


def test_at_round_penalty_appeal_and_stale_responses(base_url):
    manager, browser = _launch_browser()
    page = browser.new_page()
    try:
        page.goto(base_url, wait_until="networkidle")
        # Seed rounds: AB/CD in round 1, AC/BD in round 2, AD/BC in round 3.
        # After round 2 the table is C(6), A(3), B(3), D(0).
        round_input = page.locator('[data-testid="round-input"]')
        calculate = page.get_by_role("button", name="计算截至轮次名次", exact=True)

        round_input.fill("2")
        calculate.click()
        expect(page.locator('[data-testid="round-result-version"]')).to_have_text(
            "当前请求版本：1"
        )
        assert _round_teams(page) == ["C", "A", "B", "D"]
        # rank, team, match points, deduction, adjusted points
        assert _round_row(page, "C")[2:5] == ["6", "0", "6"]

        # A 4-point deduction for C effective from round 2. Editing the
        # penalty immediately retires the version-1 explanation.
        page.get_by_role("button", name="添加处罚").click()
        penalty_row = page.locator(".penalty-row").first
        penalty_row.locator('input[aria-label="处罚编号"]').fill("P1")
        penalty_row.locator('select[aria-label="处罚球队"]').select_option(label="C")
        penalty_row.locator('input[aria-label="处罚轮次"]').fill("2")
        penalty_row.locator('input[aria-label="处罚扣分"]').fill("4")
        expect(page.locator('[data-testid="round-standings-card"]')).to_have_count(0)
        expect(page.locator('[data-testid="round-trace-card"]')).to_have_count(0)

        calculate.click()
        expect(page.locator('[data-testid="round-result-version"]')).to_have_text(
            "当前请求版本：2"
        )
        # The deduction drops C out of the lead and creates a new A/B tie
        # group that is split by their head-to-head match.
        assert _round_teams(page) == ["A", "B", "C", "D"]
        assert _round_row(page, "C")[2:5] == ["6", "4", "2"]
        trace = page.locator('[data-testid="round-trace-card"]')
        expect(trace).to_contain_text("总积分并列组")
        expect(trace).to_contain_text("球队：A, B")

        # An appeal effective in the same round as the penalty revokes the
        # deduction entirely; C is restored to the top.
        page.get_by_role("button", name="添加申诉").click()
        appeal_row = page.locator(".appeal-row").first
        appeal_row.locator('select[aria-label="申诉处罚"]').select_option(label="P1")
        appeal_row.locator('input[aria-label="申诉轮次"]').fill("2")
        expect(page.locator('[data-testid="round-standings-card"]')).to_have_count(0)

        calculate.click()
        expect(page.locator('[data-testid="round-result-version"]')).to_have_text(
            "当前请求版本：3"
        )
        assert _round_teams(page) == ["C", "A", "B", "D"]
        assert _round_row(page, "C")[2:5] == ["6", "0", "6"]

        # Out-of-order responses: hold every request, ask for round 3, then
        # switch to round 1 and ask again.  The newer round-1 response
        # completes first; the stale round-3 response arrives afterwards and
        # must not overwrite the page.
        held = []
        page.route("**/api/rankings/at-round", lambda route: held.append(route))

        round_input.fill("3")
        expect(page.locator('[data-testid="round-standings-card"]')).to_have_count(0)
        with page.expect_request("**/api/rankings/at-round"):
            calculate.click()
        assert len(held) == 1

        round_input.fill("1")
        with page.expect_request("**/api/rankings/at-round"):
            calculate.click()
        assert len(held) == 2

        stale, fresh = held[0], held[1]
        stale_id = json.loads(stale.request.post_data)["request_id"]
        fresh_id = json.loads(fresh.request.post_data)["request_id"]
        assert fresh_id == stale_id + 1

        fresh.fulfill(response=fresh.fetch())
        expect(page.locator('[data-testid="round-result-version"]')).to_have_text(
            f"当前请求版本：{fresh_id}"
        )
        assert _round_teams(page) == ["A", "C", "B", "D"]

        stale.fulfill(response=stale.fetch())
        page.wait_for_timeout(400)
        expect(page.locator('[data-testid="round-result-version"]')).to_have_text(
            f"当前请求版本：{fresh_id}"
        )
        assert _round_teams(page) == ["A", "C", "B", "D"]
    finally:
        browser.close()
        manager.stop()
