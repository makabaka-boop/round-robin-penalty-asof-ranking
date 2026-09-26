from app.api import create_app


def client():
    return create_app().test_client()


def base_payload(round_no=2, request_id=1):
    return {
        "request_id": request_id,
        "round": round_no,
        "teams": ["A", "B", "C", "D"],
        "matches": [
            {"home": "A", "away": "B", "home_score": 1, "away_score": 0, "round": 1},
            {"home": "C", "away": "D", "home_score": 1, "away_score": 0, "round": 1},
            {"home": "C", "away": "A", "home_score": 1, "away_score": 0, "round": 2},
            {"home": "B", "away": "D", "home_score": 1, "away_score": 0, "round": 2},
        ],
        "penalties": [{"id": "P1", "team": "C", "round": 2, "points": 4}],
        "appeals": [],
    }


def order(data):
    return [row["team"] for row in data["standings"]]


def test_at_round_endpoint_returns_points_breakdown_and_trace():
    response = client().post("/api/rankings/at-round", json=base_payload())
    assert response.status_code == 200
    data = response.get_json()
    assert data["request_id"] == 1
    assert data["round"] == 2
    assert order(data) == ["A", "B", "C", "D"]

    row_c = next(row for row in data["standings"] if row["team"] == "C")
    assert row_c["match_points"] == 6
    assert row_c["deduction"] == 4
    assert row_c["points"] == 2

    first = data["tiebreakers"][0]
    assert first["basis"] == "total_points"
    assert first["points"]["A"] == {
        "id": "A",
        "match_points": 3,
        "deduction": 0,
        "points": 3,
    }


def test_at_round_endpoint_appeal_restores_same_round():
    payload = base_payload()
    payload["appeals"] = [{"penalty_id": "P1", "round": 2}]
    data = client().post("/api/rankings/at-round", json=payload).get_json()
    assert order(data) == ["C", "A", "B", "D"]
    row_c = next(row for row in data["standings"] if row["team"] == "C")
    assert row_c["deduction"] == 0
    assert row_c["points"] == 6


def test_at_round_endpoint_rejects_invalid_payloads_wholesale():
    def expect_400(**overrides):
        payload = base_payload()
        payload.update(overrides)
        response = client().post("/api/rankings/at-round", json=payload)
        assert response.status_code == 400
        return response.get_json()["error"]

    assert "unknown penalty" in expect_400(
        appeals=[{"penalty_id": "nope", "round": 2}]
    )
    assert "more than once" in expect_400(
        appeals=[{"penalty_id": "P1", "round": 2}, {"penalty_id": "P1", "round": 3}]
    )
    assert "earlier" in expect_400(appeals=[{"penalty_id": "P1", "round": 1}])
    assert "round" in expect_400(round=0)
    assert "round" in expect_400(round="2")

    response = client().post("/api/rankings/at-round", data="not json")
    assert response.status_code == 400


def test_at_round_responses_are_stateless_and_versioned():
    # Two requests for different rounds are independent; each response
    # carries its own request_id and round, so a late response can always
    # be told apart from a fresh one.
    first = client().post(
        "/api/rankings/at-round", json=base_payload(round_no=1, request_id=10)
    )
    second = client().post(
        "/api/rankings/at-round", json=base_payload(round_no=2, request_id=11)
    )
    assert first.status_code == second.status_code == 200
    first, second = first.get_json(), second.get_json()
    assert (first["request_id"], first["round"]) == (10, 1)
    assert (second["request_id"], second["round"]) == (11, 2)
    # Round 1 has no deduction yet; round 2 does.
    assert order(first) == ["A", "C", "B", "D"]
    assert order(second) == ["A", "B", "C", "D"]


def test_original_rankings_endpoint_is_unchanged():
    response = client().post(
        "/api/rankings",
        json={
            "request_id": 3,
            "teams": ["A", "B", "C", "D"],
            "matches": [
                {"home": "A", "away": "B", "home_score": 1, "away_score": 0}
            ],
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["request_id"] == 3
    assert data["standings"][0]["team"] == "A"
    assert "match_points" not in data["standings"][0]
