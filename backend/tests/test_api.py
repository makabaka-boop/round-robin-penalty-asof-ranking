from app.api import create_app


def client():
    return create_app().test_client()


def test_rankings_endpoint_returns_order_and_trace():
    response = client().post(
        "/api/rankings",
        json={
            "request_id": 11,
            "teams": ["A", "B", "C", "D"],
            "matches": [
                {"home": "A", "away": "B", "home_score": 1, "away_score": 0},
                {"home": "B", "away": "C", "home_score": 1, "away_score": 0},
                {"home": "C", "away": "A", "home_score": 1, "away_score": 0},
                {"home": "A", "away": "D", "home_score": 1, "away_score": 0},
                {"home": "B", "away": "D", "home_score": 1, "away_score": 0},
                {"home": "C", "away": "D", "home_score": 1, "away_score": 0},
            ],
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["request_id"] == 11
    assert [row["team"] for row in data["standings"]] == ["A", "B", "C", "D"]
    assert data["tiebreakers"][0]["basis"] == "total_points"
    assert data["tiebreakers"][1]["basis"] == "global_tiebreakers"


def test_rankings_endpoint_rejects_bad_payload():
    response = client().post(
        "/api/rankings",
        json={"teams": ["A", "B", "C"]},
    )
    assert response.status_code == 400
    assert "4 and 12" in response.get_json()["error"]

    response = client().post("/api/rankings", data="not json")
    assert response.status_code == 400


def test_health_endpoint():
    assert client().get("/health").get_json() == {"status": "ok"}


def _as_of_payload(**overrides):
    payload = {
        "request_id": 3,
        "teams": ["A", "B", "C", "D"],
        "matches": [
            {"home": "A", "away": "C", "home_score": 1, "away_score": 0, "round": 1},
            {"home": "B", "away": "D", "home_score": 1, "away_score": 0, "round": 1},
            {"home": "A", "away": "B", "home_score": 0, "away_score": 0, "round": 2},
            {"home": "C", "away": "D", "home_score": 1, "away_score": 0, "round": 2},
        ],
        "penalties": [
            {"id": "P1", "team": "A", "effective_round": 2, "deduction": 2}
        ],
        "appeals": [{"penalty_id": "P1", "effective_round": 3}],
        "as_of_round": 2,
    }
    payload.update(overrides)
    return payload


def test_as_of_round_endpoint_filters_events_and_reports_breakdown():
    response = client().post("/api/rankings/as-of-round", json=_as_of_payload())
    assert response.status_code == 200
    data = response.get_json()
    assert data["request_id"] == 3
    assert data["as_of_round"] == 2
    assert data["latest_played_round"] == 2
    rows = {row["team"]: row for row in data["standings"]}
    # A has 4 match points but the round-2 penalty is active: adjusted 2.
    assert rows["A"]["match_points"] == 4
    assert rows["A"]["deductions"] == 2
    assert rows["A"]["adjusted_points"] == 2
    assert rows["B"]["match_points"] == 4
    assert rows["B"]["adjusted_points"] == 4
    assert [row["team"] for row in data["standings"]] == ["B", "C", "A", "D"]


def test_as_of_round_endpoint_restores_on_appeal_and_ignores_later_games():
    # No round-3 match exists, yet the round-3 appeal vacates the penalty and
    # restores A to the top group.
    response = client().post(
        "/api/rankings/as-of-round", json=_as_of_payload(as_of_round=3)
    )
    assert response.status_code == 200
    data = response.get_json()
    rows = {row["team"]: row for row in data["standings"]}
    assert rows["A"]["deductions"] == 0
    assert rows["A"]["adjusted_points"] == 4
    assert data["latest_played_round"] == 2


def test_as_of_round_endpoint_out_of_order_responses_are_independent():
    # The server holds no state: a late response for round 1 can never alter
    # the round-3 view because every request echoes its own request id and
    # computes its own snapshot.
    late = client().post(
        "/api/rankings/as-of-round",
        json=_as_of_payload(request_id=1, as_of_round=1),
    )
    fresh = client().post(
        "/api/rankings/as-of-round",
        json=_as_of_payload(request_id=2, as_of_round=3),
    )
    late_data, fresh_data = late.get_json(), fresh.get_json()
    assert late_data["request_id"] == 1
    assert late_data["as_of_round"] == 1
    assert late_data["standings"][0]["deductions"] == 0
    assert fresh_data["request_id"] == 2
    assert fresh_data["as_of_round"] == 3
    a_row = next(row for row in fresh_data["standings"] if row["team"] == "A")
    assert a_row["deductions"] == 0


def test_as_of_round_endpoint_rejects_invalid_appeal():
    response = client().post(
        "/api/rankings/as-of-round",
        json=_as_of_payload(appeals=[{"penalty_id": "GHOST", "effective_round": 2}]),
    )
    assert response.status_code == 400
    assert "unknown penalty" in response.get_json()["error"]

    response = client().post(
        "/api/rankings/as-of-round",
        json=_as_of_payload(appeals=[{"penalty_id": "P1", "effective_round": 1}]),
    )
    assert response.status_code == 400
    assert "before the penalty" in response.get_json()["error"]

    response = client().post(
        "/api/rankings/as-of-round",
        json=_as_of_payload(as_of_round=-1),
    )
    assert response.status_code == 400

    response = client().post(
        "/api/rankings/as-of-round", data="not json"
    )
    assert response.status_code == 400
