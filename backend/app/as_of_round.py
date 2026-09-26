"""Standings as they actually stood at the end of a given round.

Penalties are only applied while they were in force: each penalty carries an
``effective_round`` and a unique id, while an appeal references exactly one
existing penalty and vacates its deduction starting from its own
``effective_round`` (which must not be earlier than the penalty's).  Only
matches with ``round <= as_of_round`` are played as far as this view is
concerned; later matches and later discipline events must not leak into an
earlier table.

Raw match points and global goals come from the played matches alone.
Deductions change only the value used for the root points grouping;
head-to-head comparisons inside a group and the global goal-difference
fallback keep using the unchanged recursive rules from :mod:`app.ranking`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .ranking import (
    TeamStat,
    _is_ascii_identifier,
    _is_score,
    calculate_stats,
    rank_teams,
)


def _is_round(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_deduction(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def validate_as_of_payload(
    payload: Any,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Validate an as-of-round payload.

    Returns teams, played matches (each carrying its ``round``), penalties,
    appeals and the requested ``as_of_round``.
    """
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    raw_teams = payload.get("teams")
    if not isinstance(raw_teams, list) or not (4 <= len(raw_teams) <= 12):
        raise ValueError("teams must contain between 4 and 12 entries")
    if not all(_is_ascii_identifier(team) for team in raw_teams):
        raise ValueError("each team id must be 1-40 non-space ASCII characters")
    if len(set(raw_teams)) != len(raw_teams):
        raise ValueError("team ids must be unique")
    teams = list(raw_teams)
    team_set = set(teams)

    as_of_round = payload.get("as_of_round")
    if not _is_round(as_of_round):
        raise ValueError("as_of_round must be a positive integer")

    raw_matches = payload.get("matches", [])
    if not isinstance(raw_matches, list):
        raise ValueError("matches must be a list")

    matches: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_matches):
        if not isinstance(item, dict):
            raise ValueError(f"match {index} must be an object")
        home = item.get("home")
        away = item.get("away")
        home_score = item.get("home_score")
        away_score = item.get("away_score")
        round_ = item.get("round")

        if home not in team_set or away not in team_set:
            raise ValueError(f"match {index} contains an unknown team")
        if home == away:
            raise ValueError(f"match {index} has the same home and away team")
        if not (_is_score(home_score) and _is_score(away_score)):
            raise ValueError(f"match {index} scores must be integers from 0 to 20")
        if not _is_round(round_):
            raise ValueError(f"match {index} round must be a positive integer")

        pair = tuple(sorted((home, away)))
        if pair in seen_pairs:
            raise ValueError(f"pair {pair[0]} and {pair[1]} appears more than once")
        seen_pairs.add(pair)
        matches.append(
            {
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "round": round_,
            }
        )

    raw_penalties = payload.get("penalties", [])
    if not isinstance(raw_penalties, list):
        raise ValueError("penalties must be a list")

    penalties: list[dict[str, Any]] = []
    seen_penalty_ids: set[str] = set()
    for index, item in enumerate(raw_penalties):
        if not isinstance(item, dict):
            raise ValueError(f"penalty {index} must be an object")
        penalty_id = item.get("id")
        team = item.get("team")
        effective_round = item.get("effective_round")
        deduction = item.get("deduction")

        if not _is_ascii_identifier(penalty_id):
            raise ValueError(f"penalty {index} id must be 1-40 non-space ASCII characters")
        if penalty_id in seen_penalty_ids:
            raise ValueError(f"penalty id {penalty_id} is duplicated")
        seen_penalty_ids.add(penalty_id)
        if team not in team_set:
            raise ValueError(f"penalty {penalty_id} references an unknown team")
        if not _is_round(effective_round):
            raise ValueError(f"penalty {penalty_id} effective_round must be a positive integer")
        if not _is_deduction(deduction):
            raise ValueError(f"penalty {penalty_id} deduction must be a positive integer")
        penalties.append(
            {
                "id": penalty_id,
                "team": team,
                "effective_round": effective_round,
                "deduction": deduction,
            }
        )

    raw_appeals = payload.get("appeals", [])
    if not isinstance(raw_appeals, list):
        raise ValueError("appeals must be a list")

    appeals: list[dict[str, Any]] = []
    appealed_penalties: set[str] = set()
    penalty_by_id = {penalty["id"]: penalty for penalty in penalties}
    for index, item in enumerate(raw_appeals):
        if not isinstance(item, dict):
            raise ValueError(f"appeal {index} must be an object")
        penalty_id = item.get("penalty_id")
        effective_round = item.get("effective_round")

        if not isinstance(penalty_id, str) or penalty_id not in penalty_by_id:
            raise ValueError(f"appeal {index} references an unknown penalty")
        if penalty_id in appealed_penalties:
            raise ValueError(f"penalty {penalty_id} has more than one appeal")
        appealed_penalties.add(penalty_id)
        if not _is_round(effective_round):
            raise ValueError(
                f"appeal for penalty {penalty_id} effective_round must be a positive integer"
            )
        if effective_round < penalty_by_id[penalty_id]["effective_round"]:
            raise ValueError(
                f"appeal for penalty {penalty_id} cannot take effect "
                "before the penalty itself"
            )
        appeals.append({"penalty_id": penalty_id, "effective_round": effective_round})

    return teams, matches, penalties, appeals, as_of_round


def active_deductions(
    penalties: list[dict[str, Any]],
    appeals: list[dict[str, Any]],
    as_of_round: int,
) -> dict[str, list[dict[str, Any]]]:
    """Penalties still in force at the end of ``as_of_round``, grouped by team."""
    appeals_by_penalty = {appeal["penalty_id"]: appeal for appeal in appeals}
    deductions: dict[str, list[dict[str, Any]]] = {}
    for penalty in penalties:
        # The event has not happened yet from the viewpoint of this round.
        if penalty["effective_round"] > as_of_round:
            continue
        appeal = appeals_by_penalty.get(penalty["id"])
        if appeal is not None and appeal["effective_round"] <= as_of_round:
            continue
        entry = {
            "id": penalty["id"],
            "team": penalty["team"],
            "deduction": penalty["deduction"],
            "effective_round": penalty["effective_round"],
        }
        if appeal is not None:
            entry["vacated_from_round"] = appeal["effective_round"]
        deductions.setdefault(penalty["team"], []).append(entry)

    for team_penalties in deductions.values():
        team_penalties.sort(
            key=lambda penalty: (penalty["effective_round"], penalty["id"].encode("ascii"))
        )
    return deductions


def compute_as_of_rankings(
    teams: list[str],
    matches: list[dict[str, Any]],
    penalties: list[dict[str, Any]],
    appeals: list[dict[str, Any]],
    as_of_round: int,
) -> dict[str, Any]:
    """Rank teams using only matches and events up to ``as_of_round``."""
    played_matches = [match for match in matches if match["round"] <= as_of_round]
    stats: dict[str, TeamStat] = calculate_stats(teams, played_matches)
    deductions = active_deductions(penalties, appeals, as_of_round)

    def deduction_total(team: str) -> int:
        return sum(penalty["deduction"] for penalty in deductions.get(team, ()))

    def adjusted_points(team: str) -> int:
        return stats[team].points - deduction_total(team)

    ranked, trace = rank_teams(
        teams, played_matches, stats, adjusted_points, "adjusted_total_points"
    )

    played_count = {
        team: sum(
            1
            for match in played_matches
            if team in (match["home"], match["away"])
        )
        for team in teams
    }
    standings = [
        {
            "rank": index + 1,
            "team": team,
            "match_points": stats[team].points,
            "deductions": deduction_total(team),
            "adjusted_points": adjusted_points(team),
            "active_penalties": [
                {"id": penalty["id"], "deduction": penalty["deduction"]}
                for penalty in deductions.get(team, ())
            ],
            "played": played_count[team],
            "goals_for": stats[team].goals_for,
            "goals_against": stats[team].goals_against,
            "goal_difference": stats[team].goal_difference,
        }
        for index, team in enumerate(ranked)
    ]

    latest_round = max((match["round"] for match in played_matches), default=0)
    return {
        "as_of_round": as_of_round,
        "latest_played_round": latest_round,
        "standings": standings,
        "tiebreakers": trace,
    }


def rank_as_of_payload(payload: Any) -> dict[str, Any]:
    teams, matches, penalties, appeals, as_of_round = validate_as_of_payload(payload)
    result = compute_as_of_rankings(teams, matches, penalties, appeals, as_of_round)
    request_id = payload.get("request_id")
    if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 0:
        request_id = uuid4().hex
    return {"request_id": request_id, "teams": teams, **result}
