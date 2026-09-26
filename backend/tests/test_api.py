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
