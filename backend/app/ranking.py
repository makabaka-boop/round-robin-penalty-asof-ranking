"""Recursive tie-breaking league ranking.

The implementation is deterministic and has no shared state.  Tie groups are
first split by points earned only in games between teams currently in the
same group.  The surviving subgroups recalculate their head-to-head points.
When that cannot separate a group, global goal difference, global goals for
and ASCII byte order of the team id are applied together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import uuid4


@dataclass(frozen=True)
class TeamStat:
    points: int
    goals_for: int
    goals_against: int

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


def _is_ascii_identifier(value: Any) -> bool:
    if not isinstance(value, str) or not (1 <= len(value) <= 40):
        return False
    return all(33 <= ord(char) <= 126 for char in value)


def _is_score(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 20


def validate_payload(payload: Any) -> tuple[list[str], list[dict[str, int | str]]]:
    """Validate API payload and return canonical teams and matches."""
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

        if home not in team_set or away not in team_set:
            raise ValueError(f"match {index} contains an unknown team")
        if home == away:
            raise ValueError(f"match {index} has the same home and away team")
        if not (_is_score(home_score) and _is_score(away_score)):
            raise ValueError(f"match {index} scores must be integers from 0 to 20")

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
            }
        )

    return teams, matches


def calculate_stats(teams: Iterable[str], matches: Iterable[dict[str, Any]]) -> dict[str, TeamStat]:
    stats = {
        team: TeamStat(points=0, goals_for=0, goals_against=0)
        for team in teams
    }

    for match in matches:
        home = match["home"]
        away = match["away"]
        hs = int(match["home_score"])
        as_ = int(match["away_score"])

        if hs > as_:
            hp, ap = 3, 0
        elif hs < as_:
            hp, ap = 0, 3
        else:
            hp = ap = 1

        stats[home] = TeamStat(
            stats[home].points + hp,
            stats[home].goals_for + hs,
            stats[home].goals_against + as_,
        )
        stats[away] = TeamStat(
            stats[away].points + ap,
            stats[away].goals_for + as_,
            stats[away].goals_against + hs,
        )

    return stats


def _internal_matches(group: set[str], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        match
        for match in matches
        if match["home"] in group and match["away"] in group
    ]


def _ascii_key(team: str) -> bytes:
    return team.encode("ascii")


def _tiebreaker_key(team: str, stats: dict[str, TeamStat]) -> tuple[int, int, bytes]:
    stat = stats[team]
    return (-stat.goal_difference, -stat.goals_for, _ascii_key(team))


def _ordered_group(teams: Iterable[str], stats: dict[str, TeamStat]) -> list[str]:
    return sorted(teams, key=lambda team: _tiebreaker_key(team, stats))


def _partition_by(
    teams: list[str], key_function
) -> list[list[str]]:
    """Partition an already ordered list into adjacent equal-key blocks."""
    if not teams:
        return []

    groups: list[list[str]] = [[teams[0]]]
    previous = key_function(teams[0])
    for team in teams[1:]:
        current = key_function(team)
        if current == previous:
            groups[-1].append(team)
        else:
            groups.append([team])
        previous = current
    return groups


def _point_values(teams: Iterable[str], stats: dict[str, TeamStat]) -> dict[str, dict[str, int | str]]:
    return {team: {"id": team, "points": stats[team].points} for team in teams}


def _tie_values(teams: Iterable[str], stats: dict[str, TeamStat]) -> dict[str, dict[str, Any]]:
    return {
        team: {
            "id": team,
            "goal_difference": stats[team].goal_difference,
            "goals_for": stats[team].goals_for,
        }
        for team in teams
    }


def _resolve_group(
    group: set[str],
    depth: int,
    stats: dict[str, TeamStat],
    matches: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> list[str]:
    # A one-team group needs no explanation.
    if len(group) == 1:
        return [next(iter(group))]

    internal_stats = calculate_stats(group, _internal_matches(group, matches))
    ordered = sorted(
        group,
        key=lambda team: (-internal_stats[team].points, _ascii_key(team)),
    )
    partitions = _partition_by(ordered, lambda team: internal_stats[team].points)

    # Internal games did not split the group.  Apply all global criteria now.
    if len(partitions) == 1:
        ordered = _ordered_group(group, stats)
        sorted_teams = sorted(group, key=_ascii_key)
        trace.append(
            {
                "depth": depth,
                "teams": sorted_teams,
                "basis": "global_tiebreakers",
                "head_to_head_points": _point_values(sorted_teams, internal_stats),
                "criteria": ["global_goal_difference", "global_goals_for", "team_id_ascii"],
                "values": _tie_values(sorted_teams, stats),
                "partitions": [[team] for team in ordered],
            }
        )
        return ordered

    trace.append(
        {
            "depth": depth,
            "teams": sorted(group, key=_ascii_key),
            "basis": "head_to_head_points",
            "head_to_head_points": _point_values(sorted(group, key=_ascii_key), internal_stats),
            "partitions": [sorted(part, key=_ascii_key) for part in partitions],
        }
    )

    result: list[str] = []
    for part in partitions:
        if len(part) == 1:
            result.extend(part)
        else:
            result.extend(_resolve_group(set(part), depth + 1, stats, matches, trace))
    return result


def compute_rankings(teams: list[str], matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Return complete order and all grouping decisions."""
    stats = calculate_stats(teams, matches)

    # A canonical order here makes recursive tie-breaking independent of the
    # order in which teams or matches were supplied.
    root_ordered = sorted(teams, key=lambda team: (-stats[team].points, _ascii_key(team)))
    root_groups = _partition_by(root_ordered, lambda team: stats[team].points)

    trace: list[dict[str, Any]] = []
    ranked: list[str] = []
    for group in root_groups:
        if len(group) == 1:
            ranked.extend(group)
        else:
            trace.append(
                {
                    "depth": 0,
                    "teams": sorted(group, key=_ascii_key),
                    "basis": "total_points",
                    "points": _point_values(
                        sorted(group, key=_ascii_key), stats
                    ),
                    "partitions": [sorted(part, key=_ascii_key) for part in [group]],
                }
            )
            ranked.extend(_resolve_group(set(group), 1, stats, matches, trace))

    standings = [
        {
            "rank": index + 1,
            "team": team,
            "points": stats[team].points,
            "played": sum(
                1
                for match in matches
                if team in (match["home"], match["away"])
            ),
            "goals_for": stats[team].goals_for,
            "goals_against": stats[team].goals_against,
            "goal_difference": stats[team].goal_difference,
        }
        for index, team in enumerate(ranked)
    ]
    return {"standings": standings, "tiebreakers": trace}


def rank_payload(payload: Any) -> dict[str, Any]:
    teams, matches = validate_payload(payload)
    result = compute_rankings(teams, matches)
    request_id = payload.get("request_id")
    if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 0:
        request_id = uuid4().hex
    return {
        "request_id": request_id,
        "teams": teams,
        **result,
    }
