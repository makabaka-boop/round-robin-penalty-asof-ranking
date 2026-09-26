import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


def _row_texts(page, table_testid):
    rows = page.locator(f'[data-testid="{table_testid}"] tbody tr').all()
    return [row.locator("td").all_inner_texts() for row in rows]


def _row_teams(page, table_testid):
    return [
        row[1]
        for row in _row_texts(page, table_testid)
    ]


def _launch_browser():
    manager = sync_playwright().start()
    try:
        browser = manager.chromium.launch(headless=True, args=["--no-sandbox"])
    except Exception as exc:  # Browser binary is unavailable in lightweight CI.
        manager.stop()
        pytest.skip(f"Chromium is not available: {exc}")
    return manager, browser


@pytest.fixture()
def browser_ctx():
    manager, browser = _launch_browser()
    context = browser.new_context()
    context.set_default_timeout(15000)
    expect.set_options(timeout=15000)
    yield context
    context.close()
    browser.close()
    manager.stop()


def _goto(page, base_url):
    page.goto(base_url, wait_until="networkidle")


def _set_seed_matches(page):
    """Reduce the six seeded pairs to a deterministic two-round season.

    Keep A-C round 1 (1:0), B-D round 1 (1:0), A-B round 2 (0:0) and
    C-D round 2 (1:0); uncheck the two remaining pairs.  Rows are in pair
    order AB, AC, AD, BC, BD, CD.
    """
    rows = page.locator('[data-testid="matches-round-card"] .match-row')
    plan = {
        0: (True, "0", "0", "2"),   # A:B draw
        1: (True, "1", "0", "1"),   # A beats C
        2: (False, "", "", "1"),    # A:D unplayed
        3: (False, "", "", "1"),    # B:C unplayed
        4: (True, "1", "0", "1"),   # B beats D
        5: (True, "1", "0", "2"),   # C beats D
    }
    for index, (played, hs, as_, round_) in plan.items():
        row = rows.nth(index)
        checkbox = row.locator('input[type="checkbox"]')
        if checkbox.is_checked() != played:
            checkbox.check() if played else checkbox.uncheck()
        if played:
            scores = row.locator(".score")
            scores.nth(0).fill(hs)
            scores.nth(1).fill(as_)
            row.locator(".round-input").fill(round_)


def _set_penalty(page, team_label, effective_round, deduction, appeal_placeholder="无"):
    penalty_row = page.locator('[data-testid="penalties-table"] tbody tr').first
    penalty_row.locator(".penalty-team").select_option(label=team_label)
    penalty_row.locator(".penalty-round").fill(str(effective_round))
    penalty_row.locator(".penalty-deduction").fill(str(deduction))
    return penalty_row


def test_edit_score_replaces_explanation_with_current_version(browser_ctx, base_url):
    page = browser_ctx.new_page()
    page.goto(base_url, wait_until="networkidle")

    # Seed: A>B, C>A, A>D, B>C, B>D, C>D. A/B/C form a 3-point cycle
    # with identical global stats, so the group falls through to global
    # tiebreakers and finally ASCII order.
    page.get_by_role("button", name="计算名次").click()
    expect(page.locator('[data-testid="result-version"]')).to_have_text("当前请求版本：1")
    expect(page.locator('[data-testid="standings-table"] tbody tr')).to_have_count(4)
    assert _row_teams(page, "standings-table") == ["A", "B", "C", "D"]
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
    assert _row_teams(page, "standings-table") == ["C", "A", "B", "D"]
    expect(page.locator('[data-testid="trace-card"]')).to_have_count(0)
    expect(page.locator('[data-testid="result-version"]')).to_have_text("当前请求版本：2")


def test_as_of_round_appeal_restores_and_same_round_vacates(browser_ctx, base_url):
    page = browser_ctx.new_page()
    _goto(page, base_url)
    page.locator('[data-testid="tab-as-of"]').click()
    _set_seed_matches(page)

    # A one-point penalty from round 2 moves A from the {A,B} top group into
    # C's group; the round-2 snapshot therefore starts B, A, C, D.
    _set_penalty(page, "A", 2, 1)
    page.locator('[data-testid="as-of-round-input"]').fill("2")
    page.locator('[data-testid="as-of-calculate"]').click()

    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text("请求版本：1")
    table = page.locator('[data-testid="as-of-standings-table"]')
    expect(table.locator("tbody tr")).to_have_count(4)
    teams = _row_teams(page, "as-of-standings-table")
    assert teams == ["B", "A", "C", "D"]
    rows = {row[1]: row for row in _row_texts(page, "as-of-standings-table")}
    # Columns: rank, team, match points, deductions, adjusted points, ...
    assert rows["A"][2] == "4"
    assert "1" in rows["A"][3]
    assert rows["A"][4] == "3"
    # The new group {A,C} is split by their played game (A beat C in R1).
    expect(page.locator('[data-testid="as-of-trace-card"]')).to_contain_text(
        "已赛比赛计算"
    )

    # Switch back to round 1: the penalty has not happened yet and the old
    # explanation disappears immediately, before any response arrives.
    page.locator('[data-testid="as-of-round-input"]').fill("1")
    expect(page.locator('[data-testid="as-of-standings-card"]')).to_have_count(0)
    expect(page.locator('[data-testid="as-of-trace-card"]')).to_have_count(0)
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text(
        "截至轮次：1"
    )
    assert _row_teams(page, "as-of-standings-table") == ["A", "B", "C", "D"]
    rows = {row[1]: row for row in _row_texts(page, "as-of-standings-table")}
    assert rows["A"][3] == "0"
    assert rows["A"][4] == "3"

    # Add an appeal effective in the same round as the penalty: even at round
    # 2 the deduction is never in force and the table is fully restored.
    page.locator('[data-testid="as-of-round-input"]').fill("2")
    penalty_row = page.locator('[data-testid="penalties-table"] tbody tr').first
    penalty_row.locator(".appeal-round").fill("2")
    # Editing an event retires the previous snapshot immediately, before the
    # replacement is calculated.
    expect(page.locator('[data-testid="as-of-standings-card"]')).to_have_count(0)
    expect(page.locator('[data-testid="as-of-trace-card"]')).to_have_count(0)
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text(
        "截至轮次：2"
    )
    assert _row_teams(page, "as-of-standings-table") == ["A", "B", "C", "D"]
    rows = {row[1]: row for row in _row_texts(page, "as-of-standings-table")}
    assert rows["A"][3] == "0"
    assert rows["A"][4] == "4"


def test_as_of_round_late_response_for_old_round_is_discarded(browser_ctx, base_url):
    page = browser_ctx.new_page()
    _goto(page, base_url)
    page.locator('[data-testid="tab-as-of"]').click()
    _set_seed_matches(page)
    _set_penalty(page, "A", 2, 1)

    # Make the round-1 response always resolve one second after round-2
    # responses, no matter which request initiated it: this deterministically
    # simulates an out-of-order arrival.
    page.evaluate(
        """
        () => {
          const original = window.fetch.bind(window);
          window.fetch = async (url, options) => {
            const response = await original(url, options);
            if (url.includes('/api/rankings/as-of-round')) {
              const body = JSON.parse(options.body);
              const delayed = body.as_of_round === 1;
              await new Promise((resolve) => setTimeout(resolve, delayed ? 1000 : 0));
            }
            return response;
          };
        }
        """
    )

    page.locator('[data-testid="as-of-round-input"]').fill("1")
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text(
        "截至轮次：1"
    )

    # Request round 2 and let its response win; the slow round-1 response
    # arrives afterwards but must not overwrite the round-2 table.
    page.locator('[data-testid="as-of-round-input"]').fill("2")
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text(
        "截至轮次：2"
    )
    assert _row_teams(page, "as-of-standings-table") == ["B", "A", "C", "D"]
    page.wait_for_timeout(1300)
    assert _row_teams(page, "as-of-standings-table") == ["B", "A", "C", "D"]
    expect(page.locator('[data-testid="as-of-result-version"]')).to_contain_text(
        "截至轮次：2"
    )


def test_as_of_round_invalid_inputs_reject_entire_request(browser_ctx, base_url):
    page = browser_ctx.new_page()
    _goto(page, base_url)
    page.locator('[data-testid="tab-as-of"]').click()
    _set_seed_matches(page)
    _set_penalty(page, "A", 2, 1)

    # Two penalties with the same id: the whole request is rejected, no table.
    page.locator('[data-testid="as-of-round-input"]').fill("2")
    page.get_by_role("button", name="新增处罚").click()
    rows = page.locator('[data-testid="penalties-table"] tbody tr')
    rows.nth(1).locator(".penalty-id").fill("P1")
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-error"]')).to_contain_text("重复")
    expect(page.locator('[data-testid="as-of-standings-card"]')).to_have_count(0)

    # An appeal earlier than its penalty is also rejected outright.
    rows.nth(1).locator(".penalty-id").fill("P2")
    rows.nth(0).locator(".appeal-round").fill("1")
    page.locator('[data-testid="as-of-calculate"]').click()
    expect(page.locator('[data-testid="as-of-error"]')).to_contain_text("申诉")
    expect(page.locator('[data-testid="as-of-standings-card"]')).to_have_count(0)
