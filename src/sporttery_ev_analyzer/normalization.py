from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from .io_utils import parse_iso_datetime, utc_now_iso
from .sources import validate_source_names

DEFAULT_TEAM_ALIASES_PATH = Path(__file__).resolve().parents[2] / "config" / "world_cup_2026_team_aliases.json"
MARKET_TYPE_ALIASES = {
    "had": "1x2",
    "1x2": "1x2",
    "win_draw_loss": "1x2",
    "match_winner_3way": "1x2",
    "moneyline_3way": "1x2",
    "hhad": "handicap_3way",
    "european_handicap": "handicap_3way",
    "handicap_3way": "handicap_3way",
    "ttg": "total_goals",
    "total_goals": "total_goals",
    "exact_total_goals": "total_goals",
    "total_goals_bucket": "total_goals",
}


def normalize_pair(
    sporttery_raw: dict[str, Any],
    market_raw: dict[str, Any],
    *,
    max_start_delta_minutes: int = 30,
    team_aliases: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    source_errors = _validate_sources(sporttery_raw, market_raw)
    alias_lookup = _build_alias_lookup(team_aliases if team_aliases is not None else _load_default_team_aliases())
    sporttery_rows = _extract_matches(sporttery_raw)
    market_rows = _extract_matches(market_raw)
    used_market_indexes: set[int] = set()
    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for sporttery_match in sporttery_rows:
        best_index, confidence = _find_market_match(
            sporttery_match,
            market_rows,
            used_market_indexes,
            max_start_delta_minutes=max_start_delta_minutes,
            alias_lookup=alias_lookup,
        )
        if best_index is None:
            unmatched.append({"source": "sporttery", "match": sporttery_match, "reason": "no_market_match"})
            continue

        used_market_indexes.add(best_index)
        market_match = market_rows[best_index]
        merged_markets, merge_unmatched = _merge_markets(sporttery_match, market_match, confidence)
        matches.extend(merged_markets)
        unmatched.extend(merge_unmatched)

    for index, market_match in enumerate(market_rows):
        if index not in used_market_indexes:
            unmatched.append({"source": market_raw.get("source", "market"), "match": market_match, "reason": "no_sporttery_match"})

    return {
        "generated_at": utc_now_iso(),
        "inputs": {
            "sporttery": _input_meta(sporttery_raw),
            "market": _input_meta(market_raw),
        },
        "source_validation": {
            "is_usable": not source_errors,
            "errors": source_errors,
        },
        "matches": matches,
        "unmatched": unmatched,
    }


def _extract_matches(raw: dict[str, Any]) -> list[dict[str, Any]]:
    payload = raw.get("raw_payload", raw)
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ValueError("raw snapshot must contain raw_payload.matches")
    return matches


def _input_meta(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": raw.get("source", "unknown"),
        "url": raw.get("url"),
        "fetched_at": raw.get("fetched_at"),
        "notes": raw.get("notes"),
    }


def _validate_sources(sporttery_raw: dict[str, Any], market_raw: dict[str, Any]) -> list[str]:
    sporttery_source = str(sporttery_raw.get("source", "unknown"))
    market_source = str(market_raw.get("source", "unknown"))
    return validate_source_names(sporttery_source, market_source)


def _find_market_match(
    sporttery_match: dict[str, Any],
    market_rows: list[dict[str, Any]],
    used_indexes: set[int],
    *,
    max_start_delta_minutes: int,
    alias_lookup: dict[str, str],
) -> tuple[int | None, float]:
    best: tuple[int | None, float] = (None, 0.0)
    for index, market_match in enumerate(market_rows):
        if index in used_indexes:
            continue
        confidence = _match_confidence(sporttery_match, market_match, max_start_delta_minutes, alias_lookup)
        if confidence > best[1]:
            best = (index, confidence)
    if best[1] < 1.0:
        return None, best[1]
    return best


def _match_confidence(
    first: dict[str, Any],
    second: dict[str, Any],
    max_start_delta_minutes: int,
    alias_lookup: dict[str, str],
) -> float:
    teams_match = (
        _canon_team(first.get("home_team"), alias_lookup) == _canon_team(second.get("home_team"), alias_lookup)
        and _canon_team(first.get("away_team"), alias_lookup) == _canon_team(second.get("away_team"), alias_lookup)
    )
    if not teams_match:
        return 0.0

    first_start = parse_iso_datetime(str(first["start_time"]))
    second_start = parse_iso_datetime(str(second["start_time"]))
    delta = abs(first_start - second_start)
    if delta > timedelta(minutes=max_start_delta_minutes):
        return 0.0
    return 1.0


def _merge_markets(
    sporttery_match: dict[str, Any],
    market_match: dict[str, Any],
    confidence: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_snapshots = [_latest_market_snapshot(market) for market in market_match.get("markets", [])]
    matched_market_ids: set[int] = set()
    market_by_key = {
        _market_key(market): (index, market)
        for index, market in enumerate(market_snapshots)
        if _market_key(market) is not None
    }
    unsupported_market_types = {
        _canon(market.get("market_type"))
        for market in market_snapshots
        if _market_key(market) is None
    }
    merged: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for sporttery_market in sporttery_match.get("markets", []):
        sporttery_market = _latest_market_snapshot(sporttery_market)
        key = _market_key(sporttery_market)
        if key is None:
            unmatched.append({"source": "sporttery", "match": sporttery_match, "market": sporttery_market, "reason": "unsupported_market_type"})
            continue
        indexed_market = market_by_key.get(key)
        if not indexed_market:
            unmatched.append(
                {
                    "source": "market",
                    "match": market_match,
                    "market": sporttery_market,
                    "reason": _no_equivalent_market_reason(key[0], unsupported_market_types),
                }
            )
            continue
        market_index, market_market = indexed_market
        matched_market_ids.add(market_index)
        match_id = sporttery_match.get("match_id") or sporttery_match.get("source_match_id")
        market_type, _, _ = key
        merged.append(
            {
                "match_id": str(match_id),
                "source_match_ids": {
                    "sporttery": sporttery_match.get("source_match_id"),
                    "market": market_match.get("source_match_id"),
                },
                "home_team": sporttery_match.get("home_team"),
                "away_team": sporttery_match.get("away_team"),
                "start_time": sporttery_match.get("start_time"),
                "market_type": market_type,
                "source_market_types": {
                    "sporttery": sporttery_market.get("market_type"),
                    "market": market_market.get("market_type"),
                },
                "handicap": sporttery_market.get("handicap"),
                "matched_status": "matched",
                "match_confidence": confidence,
                "sporttery": {
                    "odds": sporttery_market.get("odds", {}),
                    "updated_at": sporttery_market.get("updated_at"),
                },
                "market": {
                    "odds": market_market.get("odds", {}),
                    "updated_at": market_market.get("updated_at"),
                },
            }
        )
    for index, market in enumerate(market_snapshots):
        if index not in matched_market_ids and _market_key(market) is None:
            unmatched.append({"source": "market", "match": market_match, "market": market, "reason": "unsupported_market_type"})
    return merged, unmatched


def _load_default_team_aliases() -> dict[str, list[str]]:
    if not DEFAULT_TEAM_ALIASES_PATH.exists():
        return {}
    with DEFAULT_TEAM_ALIASES_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("team aliases must be a JSON object")
    return {str(team): [str(alias) for alias in aliases] for team, aliases in data.items()}


def _build_alias_lookup(team_aliases: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in team_aliases.items():
        canonical_key = _canon(canonical)
        lookup[canonical_key] = canonical_key
        for alias in aliases:
            lookup[_canon(alias)] = canonical_key
    return lookup


def _canon_team(value: Any, alias_lookup: dict[str, str]) -> str:
    value_key = _canon(value)
    return alias_lookup.get(value_key, value_key)


def _market_key(market: dict[str, Any]) -> tuple[str, str, frozenset[str]] | None:
    market_type = MARKET_TYPE_ALIASES.get(_canon(market.get("market_type")))
    if market_type is None:
        return None
    odds = market.get("odds", {})
    if not isinstance(odds, dict) or not odds:
        return None
    return market_type, str(market.get("handicap", "")), frozenset(str(outcome) for outcome in odds)


def _no_equivalent_market_reason(sporttery_market_type: str, unsupported_market_types: set[str]) -> str:
    if sporttery_market_type == "handicap_3way" and "asian_handicap" in unsupported_market_types:
        return "asian_handicap_is_not_equivalent_to_sporttery_3way_handicap"
    if sporttery_market_type == "total_goals" and "over_under" in unsupported_market_types:
        return "over_under_is_not_equivalent_to_sporttery_total_goals"
    return "no_equivalent_market"


def _latest_market_snapshot(market: dict[str, Any]) -> dict[str, Any]:
    history = market.get("odds_history", [])
    if not isinstance(history, list) or not history:
        snapshot = dict(market)
        snapshot["updated_at"] = market.get("updated_at") or market.get("published_at")
        return snapshot

    latest = max(history, key=lambda row: parse_iso_datetime(str(row.get("updated_at") or row.get("published_at"))))
    snapshot = dict(market)
    snapshot["odds"] = latest.get("odds", {})
    snapshot["updated_at"] = latest.get("updated_at") or latest.get("published_at")
    return snapshot


def _canon(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "")
