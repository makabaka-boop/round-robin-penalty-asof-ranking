import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


def _row_teams(page):
    return page.locator('[data-testid="standings-table"] tbody tr td:nth-child(2)').all_inner_texts()


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
