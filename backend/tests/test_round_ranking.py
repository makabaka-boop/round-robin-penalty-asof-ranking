from app.round_ranking import (
    compute_round_rankings,
    effective_deductions,
    rank_round_payload,
    validate_round_payload,
)

# Shared scenario:
#   round 1: A 1:0 B, C 1:0 D
#   round 2: C 1:0 A, B 1:0 D
#   round 3: A 2:0 D, B 1:0 C
# Without deductions the table is [A, C, B, D] after round 1,
# [C, A, B, D] after round 2 and [A, B, C, D] after round 3.
TEAMS = ["A", "B", "C", "D"]
MATCHES = [
    {"home": "A", "away": "B", "home_score": 1, "away_score": 0, "round": 1},
    {"home": "C", "away": "D", "home_score": 1, "away_score": 0, "round": 1},
    {"home": "C", "away": "A", "home_score": 1, "away_score": 0, "round": 2},
    {"home": "B", "away": "D", "home_score": 1, "away_score": 0, "round": 2},
    {"home": "A", "away": "D", "home_score": 2, "away_score": 0, "round": 3},
    {"home": "B", "away": "C", "home_score": 1, "away_score": 0, "round": 3},
]
PENALTY_C = {"id": "P1", "team": "C", "round": 2, "points": 4}


def teams_from(result):
    return [row["team"] for row in result["standings"]]


def row_of(result, team):
    return next(row for row in result["standings"] if row["team"] == team)


def rank(round_no, penalties=None, appeals=None):
    return compute_round_rankings(
        TEAMS, MATCHES, penalties or [], appeals or [], round_no
    )


def test_deduction_changes_tie_groups():
    # C loses 4 points from round 2 and drops out of the lead; A and B form
    # a new tied group at 3 adjusted points that is split by head-to-head.
    result = rank(2, penalties=[PENALTY_C])
    assert teams_from(result) == ["A", "B", "C", "D"]

    row_c = row_of(result, "C")
    assert row_c["match_points"] == 6
    assert row_c["deduction"] == 4
    assert row_c["points"] == 2

    first = result["tiebreakers"][0]
    assert first["basis"] == "total_points"
    assert first["teams"] == ["A", "B"]
    assert first["points"] == {
        "A": {"id": "A", "match_points": 3, "deduction": 0, "points": 3},
        "B": {"id": "B", "match_points": 3, "deduction": 0, "points": 3},
    }
    # A beat B in round 1, so the head-to-head split puts A first.
    second = result["tiebreakers"][1]
    assert second["basis"] == "head_to_head_points"
    assert second["partitions"] == [["A"], ["B"]]


def test_penalty_applies_only_from_its_own_round():
    # Round 1 is over before the penalty exists, so the table is untouched.
    assert teams_from(rank(1, penalties=[PENALTY_C])) == ["A", "C", "B", "D"]
    assert row_of(rank(1, penalties=[PENALTY_C]), "C")["deduction"] == 0
    # From round 2 onward the deduction is part of the table.
    assert teams_from(rank(2, penalties=[PENALTY_C])) == ["A", "B", "C", "D"]
    assert teams_from(rank(3, penalties=[PENALTY_C])) == ["A", "B", "C", "D"]


def test_appeal_restores_points_from_its_round():
    appeal = {"penalty_id": "P1", "round": 3}
    # Before the appeal round the deduction still applies.
    before = rank(2, penalties=[PENALTY_C], appeals=[appeal])
    assert teams_from(before) == ["A", "B", "C", "D"]
    assert row_of(before, "C")["deduction"] == 4
    # From the appeal round onward the deduction is revoked and C rejoins
    # the three-way tie at the top (decided by global goal difference).
    after = rank(3, penalties=[PENALTY_C], appeals=[appeal])
    assert teams_from(after) == ["A", "B", "C", "D"]
    row_c = row_of(after, "C")
    assert row_c["match_points"] == 6
    assert row_c["deduction"] == 0
    assert row_c["points"] == 6
    assert after["tiebreakers"][0]["teams"] == ["A", "B", "C"]


def test_appeal_in_same_round_as_penalty_never_deducts():
    appeal = {"penalty_id": "P1", "round": 2}
    result = rank(2, penalties=[PENALTY_C], appeals=[appeal])
    assert teams_from(result) == ["C", "A", "B", "D"]
    assert row_of(result, "C")["deduction"] == 0
    # The only tie left is A/B on match points; C stands alone at the top.
    assert result["tiebreakers"][0]["teams"] == ["A", "B"]


def test_events_after_selected_round_are_ignored():
    late_penalty = {"id": "P9", "team": "A", "round": 4, "points": 5}
    late_appeal = {"penalty_id": "P9", "round": 4}
    result = rank(3, penalties=[late_penalty], appeals=[late_appeal])
    row_a = row_of(result, "A")
    # The round-4 penalty/appeal and matches do not leak into round 3.
    assert row_a["match_points"] == 6
    assert row_a["deduction"] == 0
    assert row_a["played"] == 3
    assert teams_from(result) == ["A", "B", "C", "D"]


def test_effective_deductions_stack_multiple_penalties():
    penalties = [
        {"id": "P1", "team": "C", "round": 1, "points": 2},
        {"id": "P2", "team": "C", "round": 2, "points": 3},
        {"id": "P3", "team": "B", "round": 3, "points": 1},
    ]
    appeals = [{"penalty_id": "P1", "round": 2}]
    assert effective_deductions(TEAMS, penalties, appeals, 1) == {
        "A": 0,
        "B": 0,
        "C": 2,
        "D": 0,
    }
    assert effective_deductions(TEAMS, penalties, appeals, 2) == {
        "A": 0,
        "B": 0,
        "C": 3,
        "D": 0,
    }
    assert effective_deductions(TEAMS, penalties, appeals, 3) == {
        "A": 0,
        "B": 1,
        "C": 3,
        "D": 0,
    }


def test_round_flow_is_input_order_independent():
    penalties = [PENALTY_C, {"id": "P2", "team": "A", "round": 3, "points": 1}]
    appeals = [{"penalty_id": "P1", "round": 3}]
    shuffled_matches = list(reversed(MATCHES))
    shuffled_penalties = list(reversed(penalties))
    assert compute_round_rankings(
        TEAMS, MATCHES, penalties, appeals, 3
    ) == compute_round_rankings(
        list(reversed(TEAMS)), shuffled_matches, shuffled_penalties, appeals, 3
    )


def payload(round_no=2, **overrides):
    base = {
        "request_id": 5,
        "round": round_no,
        "teams": list(TEAMS),
        "matches": [dict(match) for match in MATCHES],
        "penalties": [dict(PENALTY_C)],
        "appeals": [],
    }
    base.update(overrides)
    return base


def test_rank_round_payload_echoes_version_and_round():
    result = rank_round_payload(payload(2, appeals=[{"penalty_id": "P1", "round": 2}]))
    assert result["request_id"] == 5
    assert result["round"] == 2
    assert teams_from(result) == ["C", "A", "B", "D"]
    for row in result["standings"]:
        assert {
            "rank",
            "team",
            "match_points",
            "deduction",
            "points",
            "played",
            "goals_for",
            "goals_against",
            "goal_difference",
        } <= set(row)


def test_validation_rejects_invalid_rounds():
    def expect_error(round_no, fragment="round"):
        try:
            validate_round_payload(payload(round_no))
        except ValueError as exc:
            assert fragment in str(exc)
        else:
            raise AssertionError("validation should fail")

    expect_error(0)
    expect_error(-2)
    expect_error(1.5)
    expect_error("2")
    expect_error(None)


def test_validation_rejects_bad_event_references_and_duplicates():
    def expect_error(overrides, fragment):
        try:
            validate_round_payload(payload(2, **overrides))
        except ValueError as exc:
            assert fragment in str(exc)
        else:
            raise AssertionError("validation should fail")

    # Appeal must reference an existing penalty.
    expect_error(
        {"appeals": [{"penalty_id": "nope", "round": 2}]}, "unknown penalty"
    )
    # The same penalty cannot be appealed twice.
    expect_error(
        {
            "appeals": [
                {"penalty_id": "P1", "round": 2},
                {"penalty_id": "P1", "round": 3},
            ]
        },
        "more than once",
    )
    # The appeal round must not be earlier than the penalty round.
    expect_error({"appeals": [{"penalty_id": "P1", "round": 1}]}, "earlier")
    # Penalty ids must be unique.
    expect_error(
        {"penalties": [dict(PENALTY_C), dict(PENALTY_C)]}, "more than once"
    )
    # Penalties must reference a known team.
    expect_error(
        {"penalties": [{"id": "P2", "team": "Z", "round": 1, "points": 1}]},
        "unknown team",
    )
    # Deductions must be positive integers.
    expect_error(
        {"penalties": [{"id": "P2", "team": "A", "round": 1, "points": 0}]},
        "points",
    )
    # Matches must carry a valid round.
    expect_error(
        {
            "matches": [
                {"home": "A", "away": "B", "home_score": 1, "away_score": 0}
            ]
        },
        "round",
    )
