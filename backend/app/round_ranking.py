"""As-of-round rankings with disciplinary deductions and appeals.

Every match carries the round it was played in.  A penalty has a unique id,
a team, the round it takes effect and the number of points deducted.  An
appeal references exactly one existing penalty and revokes its deduction
from the appeal round onward; the appeal round must not be earlier than the
penalty round.  Anything scheduled after the requested round is ignored, so
a historical table never absorbs later punishments.

Grouping reuses the original recursive rules: match points plus the
currently effective deductions form the total-points groups, head-to-head
records inside a group still come only from played matches, and the global
goal-difference/goals-for/ASCII fallbacks are unchanged.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .ranking import (
    _ascii_key,
    _is_ascii_identifier,
    _is_score,
    _partition_by,
    _resolve_group,
    calculate_stats,
)


def _is_round(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_deduction(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def validate_round_payload(
    payload: Any,
) -> tuple[
    int,
    list[str],
    list[dict[str, int | str]],
    list[dict[str, int | str]],
    list[dict[str, int | str]],
]:
    """Validate the as-of-round payload.

    Returns ``(round, teams, matches, penalties, appeals)``.  Any invalid
    reference, duplicate appeal or invalid round rejects the whole payload.
    """
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    round_no = payload.get("round")
    if not _is_round(round_no):
        raise ValueError("round must be an integer >= 1")

    raw_teams = payload.get("teams")
    if not isinstance(raw_teams, list) or not (4 <= len(raw_teams) <= 12):
        raise ValueError("teams must contain between 4 and 12 entries")
    if not all(_is_ascii_identifier(team) for team in raw_teams):
        raise ValueError("each team id must be 1-40 non-space ASCII characters")
    if len(set(raw_teams)) != len(raw_teams):
        raise ValueError("team ids must be unique")
    teams = list(raw_teams)
    team_set = set(teams)

    raw_matches = payload.get("matches", [])
    if not isinstance(raw_matches, list):
        raise ValueError("matches must be a list")

    matches: list[dict[str, int | str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_matches):
        if not isinstance(item, dict):
            raise ValueError(f"match {index} must be an object")
        home = item.get("home")
        away = item.get("away")
        home_score = item.get("home_score")
        away_score = item.get("away_score")
        match_round = item.get("round")

        if home not in team_set or away not in team_set:
            raise ValueError(f"match {index} contains an unknown team")
        if home == away:
            raise ValueError(f"match {index} has the same home and away team")
        if not (_is_score(home_score) and _is_score(away_score)):
            raise ValueError(f"match {index} scores must be integers from 0 to 20")
        if not _is_round(match_round):
            raise ValueError(f"match {index} round must be an integer >= 1")

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
                "round": match_round,
            }
        )

    raw_penalties = payload.get("penalties", [])
    if not isinstance(raw_penalties, list):
        raise ValueError("penalties must be a list")

    penalties: list[dict[str, int | str]] = []
    seen_penalty_ids: set[str] = set()
    for index, item in enumerate(raw_penalties):
        if not isinstance(item, dict):
            raise ValueError(f"penalty {index} must be an object")
        penalty_id = item.get("id")
        team = item.get("team")
        penalty_round = item.get("round")
        points = item.get("points")

        if not _is_ascii_identifier(penalty_id):
            raise ValueError(f"penalty {index} id must be 1-40 non-space ASCII characters")
        if penalty_id in seen_penalty_ids:
            raise ValueError(f"penalty id {penalty_id} appears more than once")
        seen_penalty_ids.add(penalty_id)
        if team not in team_set:
            raise ValueError(f"penalty {index} references an unknown team")
        if not _is_round(penalty_round):
            raise ValueError(f"penalty {index} round must be an integer >= 1")
        if not _is_deduction(points):
            raise ValueError(f"penalty {index} points must be an integer >= 1")
        penalties.append(
            {"id": penalty_id, "team": team, "round": penalty_round, "points": points}
        )

    raw_appeals = payload.get("appeals", [])
    if not isinstance(raw_appeals, list):
        raise ValueError("appeals must be a list")

    penalty_rounds = {penalty["id"]: penalty["round"] for penalty in penalties}
    appeals: list[dict[str, int | str]] = []
    appealed: set[str] = set()
    for index, item in enumerate(raw_appeals):
        if not isinstance(item, dict):
            raise ValueError(f"appeal {index} must be an object")
        penalty_id = item.get("penalty_id")
        appeal_round = item.get("round")

        if penalty_id not in penalty_rounds:
            raise ValueError(f"appeal {index} references an unknown penalty")
        if penalty_id in appealed:
            raise ValueError(f"penalty {penalty_id} is appealed more than once")
        appealed.add(penalty_id)
        if not _is_round(appeal_round):
            raise ValueError(f"appeal {index} round must be an integer >= 1")
        if appeal_round < penalty_rounds[penalty_id]:
            raise ValueError(
                f"appeal {index} round must not be earlier than the penalty round"
            )
        appeals.append({"penalty_id": penalty_id, "round": appeal_round})

    return round_no, teams, matches, penalties, appeals


def effective_deductions(
    teams: list[str],
    penalties: list[dict[str, Any]],
    appeals: list[dict[str, Any]],
    round_no: int,
) -> dict[str, int]:
    """Points deducted per team at the end of ``round_no``.

    A penalty applies from its own round onward unless an appeal with a
    round less than or equal to ``round_no`` has revoked it.
    """
    appeal_rounds = {appeal["penalty_id"]: appeal["round"] for appeal in appeals}
    deductions = {team: 0 for team in teams}
    for penalty in penalties:
        if penalty["round"] > round_no:
            continue
        appeal_round = appeal_rounds.get(penalty["id"])
        if appeal_round is not None and appeal_round <= round_no:
            continue
        deductions[penalty["team"]] += penalty["points"]
    return deductions


def compute_round_rankings(
    teams: list[str],
    matches: list[dict[str, Any]],
    penalties: list[dict[str, Any]],
    appeals: list[dict[str, Any]],
    round_no: int,
) -> dict[str, Any]:
    """Rank as of ``round_no``; later matches and events are ignored."""
    played = [match for match in matches if match["round"] <= round_no]
    stats = calculate_stats(teams, played)
    deductions = effective_deductions(teams, penalties, appeals, round_no)
    adjusted = {team: stats[team].points - deductions[team] for team in teams}

    # A canonical order here keeps the outcome independent of input order.
    root_ordered = sorted(teams, key=lambda team: (-adjusted[team], _ascii_key(team)))
    root_groups = _partition_by(root_ordered, lambda team: adjusted[team])

    trace: list[dict[str, Any]] = []
    ranked: list[str] = []
    for group in root_groups:
        if len(group) == 1:
            ranked.extend(group)
        else:
            ordered_group = sorted(group, key=_ascii_key)
            trace.append(
                {
                    "depth": 0,
                    "teams": ordered_group,
                    "basis": "total_points",
                    "points": {
                        team: {
                            "id": team,
                            "match_points": stats[team].points,
                            "deduction": deductions[team],
                            "points": adjusted[team],
                        }
                        for team in ordered_group
                    },
                    "partitions": [ordered_group],
                }
            )
            ranked.extend(_resolve_group(set(group), 1, stats, played, trace))

    standings = [
        {
            "rank": index + 1,
            "team": team,
            "match_points": stats[team].points,
            "deduction": deductions[team],
            "points": adjusted[team],
            "played": sum(
                1
                for match in played
                if team in (match["home"], match["away"])
            ),
            "goals_for": stats[team].goals_for,
            "goals_against": stats[team].goals_against,
            "goal_difference": stats[team].goal_difference,
        }
        for index, team in enumerate(ranked)
    ]
    return {"standings": standings, "tiebreakers": trace}


def rank_round_payload(payload: Any) -> dict[str, Any]:
    round_no, teams, matches, penalties, appeals = validate_round_payload(payload)
    result = compute_round_rankings(teams, matches, penalties, appeals, round_no)
    request_id = payload.get("request_id")
    if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 0:
        request_id = uuid4().hex
    return {
        "request_id": request_id,
        "round": round_no,
        "teams": teams,
        **result,
    }
