import pytest

from app.as_of_round import (
    active_deductions,
    compute_as_of_rankings,
    rank_as_of_payload,
    validate_as_of_payload,
)


def match(home, away, hs, as_, round_):
    return {
        "home": home,
        "away": away,
        "home_score": hs,
        "away_score": as_,
        "round": round_,
    }


def penalty(penalty_id, team, effective_round, deduction):
    return {
        "id": penalty_id,
        "team": team,
        "effective_round": effective_round,
        "deduction": deduction,
    }


def appeal(penalty_id, effective_round):
    return {"penalty_id": penalty_id, "effective_round": effective_round}


def teams_from(result):
    return [row["team"] for row in result["standings"]]


def row_by_team(result, team):
    return next(row for row in result["standings"] if row["team"] == team)


# Round 1: A beats C, B beats D.  Round 2: A draws B, C beats D.
# After round 2 A and B share four points; their direct draw cannot split
# them, so global goals decide the top pair.
def season_matches():
    return [
        match("A", "C", 1, 0, 1),
        match("B", "D", 1, 0, 1),
        match("A", "B", 0, 0, 2),
        match("C", "D", 1, 0, 2),
    ]


TEAMS = ["A", "B", "C", "D"]


def test_round_one_uses_only_round_one_matches():
    result = compute_as_of_rankings(TEAMS, season_matches(), [], [], 1)

    assert result["as_of_round"] == 1
    assert result["latest_played_round"] == 1
    # Only the two round-1 games exist in this view.
    assert [row_by_team(result, team)["played"] for team in TEAMS] == [1, 1, 1, 1]
    assert teams_from(result) == ["A", "B", "C", "D"]
    for team in ("A", "B"):
        row = row_by_team(result, team)
        assert row["match_points"] == 3
        assert row["deductions"] == 0
        assert row["adjusted_points"] == 3
        assert row["active_penalties"] == []
    for team in ("C", "D"):
        assert row_by_team(result, team)["adjusted_points"] == 0
    # Two tied groups exist ({A,B} and {C,D}); neither pair has met yet, so
    # both fall through to the global goal criteria.
    bases = [event["basis"] for event in result["tiebreakers"]]
    assert bases == [
        "adjusted_total_points",
        "global_tiebreakers",
        "adjusted_total_points",
        "global_tiebreakers",
    ]
    tied_teams = [event["teams"] for event in result["tiebreakers"] if event["basis"] == "adjusted_total_points"]
    assert tied_teams == [["A", "B"], ["C", "D"]]


def test_deduction_changes_tied_group_membership():
    # A one-point penalty in round 2 ejects A from the {A, B} four-point
    # group into C's three-point group; B stands alone at the top.
    penalties = [penalty("P1", "A", 2, 1)]

    before = compute_as_of_rankings(TEAMS, season_matches(), penalties, [], 1)
    assert teams_from(before) == ["A", "B", "C", "D"]
    assert row_by_team(before, "A")["deductions"] == 0

    result = compute_as_of_rankings(TEAMS, season_matches(), penalties, [], 2)
    assert teams_from(result) == ["B", "A", "C", "D"]

    a_row = row_by_team(result, "A")
    assert a_row["match_points"] == 4
    assert a_row["deductions"] == 1
    assert a_row["adjusted_points"] == 3
    assert a_row["active_penalties"] == [{"id": "P1", "deduction": 1}]

    b_row = row_by_team(result, "B")
    assert b_row["match_points"] == 4
    assert b_row["deductions"] == 0
    assert b_row["adjusted_points"] == 4

    # A and C are tied at 3 adjusted points; they already played in round 1
    # and A won, so head-to-head points split them.  The deduction never
    # enters that comparison.
    root = result["tiebreakers"][0]
    assert root["basis"] == "adjusted_total_points"
    assert root["teams"] == ["A", "C"]
    assert root["points"]["A"]["points"] == 3
    assert root["points"]["C"]["points"] == 3
    h2h = result["tiebreakers"][1]
    assert h2h["basis"] == "head_to_head_points"
    assert h2h["head_to_head_points"]["A"]["points"] == 3
    assert h2h["head_to_head_points"]["C"]["points"] == 0
    assert h2h["partitions"] == [["A"], ["C"]]


def test_deduction_moves_team_into_a_group_split_by_played_game():
    # Extend the season with D 0:2 A in round 3, then deduct four points
    # from A from round 3: A drops from 7 points into C's group (3 each), and
    # the two are split purely by their already played round-1 game, which
    # A won.  The deduction never enters the head-to-head comparison.
    matches = season_matches() + [match("D", "A", 0, 2, 3)]
    penalties = [penalty("P1", "A", 3, 4)]

    result = compute_as_of_rankings(TEAMS, matches, penalties, [], 3)
    assert teams_from(result) == ["B", "A", "C", "D"]

    a_row = row_by_team(result, "A")
    assert a_row["match_points"] == 7
    assert a_row["deductions"] == 4
    assert a_row["adjusted_points"] == 3
    assert row_by_team(result, "C")["adjusted_points"] == 3

    h2h_events = [
        event
        for event in result["tiebreakers"]
        if event["basis"] == "head_to_head_points" and event["teams"] == ["A", "C"]
    ]
    assert h2h_events, "A/C should be split by their played game"
    h2h = h2h_events[0]["head_to_head_points"]
    assert h2h["A"]["points"] == 3
    assert h2h["C"]["points"] == 0
    assert h2h_events[0]["partitions"] == [["A"], ["C"]]


def test_appeal_restores_points_from_appeal_round():
    penalties = [penalty("P1", "A", 2, 2)]
    appeals = [appeal("P1", 3)]

    round_two = compute_as_of_rankings(TEAMS, season_matches(), penalties, appeals, 2)
    assert row_by_team(round_two, "A")["deductions"] == 2
    assert teams_from(round_two) == ["B", "C", "A", "D"]

    # The appeal takes effect at round 3 even without a round-3 match: the
    # table must look as though the penalty had never been applied.
    round_three = compute_as_of_rankings(TEAMS, season_matches(), penalties, appeals, 3)
    assert teams_from(round_three) == ["A", "B", "C", "D"]
    a_row = row_by_team(round_three, "A")
    assert a_row["match_points"] == 4
    assert a_row["deductions"] == 0
    assert a_row["adjusted_points"] == 4
    assert a_row["active_penalties"] == []


def test_penalty_and_appeal_effective_in_same_round_never_applies():
    # An appeal may vacate starting from the penalty's own round: at every
    # visible round the deduction was never in force.
    penalties = [penalty("P1", "A", 2, 2)]
    appeals = [appeal("P1", 2)]

    assert active_deductions(penalties, appeals, 2) == {}
    result = compute_as_of_rankings(TEAMS, season_matches(), penalties, appeals, 2)
    assert teams_from(result) == ["A", "B", "C", "D"]
    assert row_by_team(result, "A")["deductions"] == 0


def test_later_rounds_do_not_leak_into_earlier_tables():
    # Round-3 events and matches must be invisible at round 2, even when
    # they would otherwise reorder teams.
    penalties = [penalty("P1", "B", 3, 6)]
    result = compute_as_of_rankings(TEAMS, season_matches(), penalties, [], 2)
    assert row_by_team(result, "B")["deductions"] == 0
    assert result["latest_played_round"] == 2

    # A duplicate pair across rounds is still rejected outright.
    all_matches = season_matches() + [match("A", "B", 5, 0, 4)]
    with pytest.raises(ValueError):
        validate_as_of_payload(
            {"teams": TEAMS, "matches": all_matches, "as_of_round": 2}
        )


def test_multiple_penalties_accumulate_and_are_listed():
    penalties = [
        penalty("P1", "A", 1, 1),
        penalty("P2", "A", 2, 2),
        penalty("P3", "B", 3, 6),
    ]
    round_one = compute_as_of_rankings(TEAMS, season_matches(), penalties, [], 1)
    a_round_one = row_by_team(round_one, "A")
    assert a_round_one["deductions"] == 1
    assert a_round_one["adjusted_points"] == 2

    round_two = compute_as_of_rankings(TEAMS, season_matches(), penalties, [], 2)
    a_row = row_by_team(round_two, "A")
    assert a_row["deductions"] == 3
    assert a_row["match_points"] - a_row["deductions"] == a_row["adjusted_points"]
    assert a_row["active_penalties"] == [
        {"id": "P1", "deduction": 1},
        {"id": "P2", "deduction": 2},
    ]
    # The round-3 penalty is not yet visible.
    assert row_by_team(round_two, "B")["deductions"] == 0


def test_payload_echoes_request_id_and_teams():
    result = rank_as_of_payload(
        {
            "request_id": 42,
            "teams": TEAMS,
            "matches": season_matches(),
            "penalties": [penalty("P1", "A", 2, 1)],
            "appeals": [],
            "as_of_round": 2,
        }
    )
    assert result["request_id"] == 42
    assert result["teams"] == TEAMS
    assert result["as_of_round"] == 2


def test_invalid_references_and_rounds_reject_whole_request():
    base_matches = season_matches()
    base_penalties = [penalty("P1", "A", 2, 1)]

    def expect_error(payload, fragment):
        with pytest.raises(ValueError) as exc_info:
            validate_as_of_payload(payload)
        assert fragment in str(exc_info.value)

    expect_error(
        {"teams": TEAMS, "matches": base_matches, "as_of_round": 0},
        "as_of_round",
    )
    expect_error(
        {"teams": TEAMS, "matches": base_matches, "as_of_round": 2.0},
        "as_of_round",
    )
    expect_error(
        {
            "teams": TEAMS,
            "matches": [{**base_matches[0], "round": 0}],
            "as_of_round": 2,
        },
        "round",
    )
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": [penalty("P1", "ZZ", 2, 1)],
            "as_of_round": 2,
        },
        "unknown team",
    )
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": [{**base_penalties[0], "deduction": 0}],
            "as_of_round": 2,
        },
        "deduction",
    )
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": [base_penalties[0], base_penalties[0]],
            "as_of_round": 2,
        },
        "duplicated",
    )
    # An appeal must reference a penalty that exists.
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": base_penalties,
            "appeals": [appeal("MISSING", 2)],
            "as_of_round": 2,
        },
        "unknown penalty",
    )
    # One appeal per penalty only.
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": base_penalties,
            "appeals": [appeal("P1", 2), appeal("P1", 3)],
            "as_of_round": 3,
        },
        "more than one appeal",
    )
    # The appeal cannot take effect before the penalty it cites.
    expect_error(
        {
            "teams": TEAMS,
            "matches": base_matches,
            "penalties": base_penalties,
            "appeals": [appeal("P1", 1)],
            "as_of_round": 2,
        },
        "before the penalty",
    )
