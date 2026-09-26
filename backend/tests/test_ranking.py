from app.ranking import compute_rankings, rank_payload, validate_payload


def match(home, away, hs, as_):
    return {
        "home": home,
        "away": away,
        "home_score": hs,
        "away_score": as_,
    }


def teams_from(result):
    return [row["team"] for row in result["standings"]]


def test_three_team_circular_group_falls_back_without_using_total_gd_alone():
    # A, B and C form a cycle and have exactly equal global stats.  Total
    # goal difference cannot decide them; the recursive internal comparison
    # also stays tied, so GF then ASCII id is used.
    teams = ["A", "B", "C", "D"]
    matches = [
        match("A", "B", 1, 0),
        match("B", "C", 1, 0),
        match("C", "A", 1, 0),
        match("A", "D", 1, 0),
        match("B", "D", 1, 0),
        match("C", "D", 1, 0),
    ]

    result = compute_rankings(teams, matches)
    assert teams_from(result) == ["A", "B", "C", "D"]
    tied_event = result["tiebreakers"][1]
    assert tied_event["basis"] == "global_tiebreakers"
    assert tied_event["teams"] == ["A", "B", "C"]
    assert tied_event["criteria"] == [
        "global_goal_difference",
        "global_goals_for",
        "team_id_ascii",
    ]
    assert tied_event["partitions"] == [["A"], ["B"], ["C"]]


def test_surviving_subgroup_recalculates_without_removed_team():
    # A, B, C and D each have six global points.  Their internal points split
    # into A, then C/D, then B.  C/D must recalculate using only their direct
    # game; C won it.  External E/F compensate the global points, proving that
    # a later subgroup does not reuse the first four-team comparison.
    teams = ["A", "B", "C", "D", "E", "F"]
    matches = [
        match("A", "B", 1, 0),
        match("A", "C", 0, 0),
        match("A", "D", 0, 0),
        match("B", "C", 1, 0),
        match("C", "D", 1, 0),
        match("D", "B", 1, 0),
        match("A", "E", 0, 0),
        match("B", "E", 1, 0),
        match("C", "E", 0, 0),
        match("D", "E", 0, 0),
        match("C", "F", 0, 0),
        match("D", "F", 0, 0),
    ]

    result = compute_rankings(teams, matches)
    assert teams_from(result) == ["A", "C", "D", "B", "E", "F"]
    bases = [event["basis"] for event in result["tiebreakers"]]
    assert bases == ["total_points", "head_to_head_points", "head_to_head_points"]

    first_split = result["tiebreakers"][1]
    assert first_split["partitions"] == [["A"], ["C", "D"], ["B"]]
    recalculated = result["tiebreakers"][2]
    assert recalculated["depth"] == 2
    assert recalculated["teams"] == ["C", "D"]
    assert recalculated["head_to_head_points"] == {
        "C": {"id": "C", "points": 3},
        "D": {"id": "D", "points": 0},
    }
    assert recalculated["partitions"] == [["C"], ["D"]]


def test_input_order_permutation_gives_same_ranking_and_trace():
    teams = ["F", "E", "D", "C", "B", "A"]
    matches = [
        match("D", "F", 0, 0),
        match("C", "F", 0, 0),
        match("D", "E", 0, 0),
        match("C", "E", 0, 0),
        match("B", "E", 1, 0),
        match("A", "E", 0, 0),
        match("D", "B", 1, 0),
        match("C", "D", 1, 0),
        match("B", "C", 1, 0),
        match("A", "D", 0, 0),
        match("A", "C", 0, 0),
        match("A", "B", 1, 0),
    ]

    canonical_teams = sorted(teams)
    canonical_matches = list(reversed(matches))
    assert compute_rankings(teams, matches) == compute_rankings(
        canonical_teams, canonical_matches
    )
    assert teams_from(compute_rankings(teams, matches)) == [
        "A",
        "C",
        "D",
        "B",
        "E",
        "F",
    ]


def test_validation_and_echo_version():
    payload = {
        "request_id": 7,
        "teams": ["A", "B", "C", "D"],
        "matches": [match("A", "B", 20, 0)],
    }
    result = rank_payload(payload)
    assert result["request_id"] == 7
    assert len(result["standings"]) == 4


def test_invalid_inputs_are_reported():
    def expect_error(payload, fragment):
        try:
            validate_payload(payload)
        except ValueError as exc:
            assert fragment in str(exc)
        else:
            raise AssertionError("validation should fail")

    expect_error({"teams": ["A", "B", "C"]}, "4 and 12")
    expect_error({"teams": ["A", "B", "C", "C"]}, "unique")
    expect_error({"teams": ["A", "B", "C", ""]}, "ASCII")
    expect_error(
        {
            "teams": ["A", "B", "C", "D"],
            "matches": [match("A", "B", 21, 0)],
        },
        "0 to 20",
    )
    expect_error(
        {
            "teams": ["A", "B", "C", "D"],
            "matches": [match("A", "B", 1, 0), match("B", "A", 0, 1)],
        },
        "more than once",
    )
