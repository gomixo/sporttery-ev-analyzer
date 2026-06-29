"""Pinnacle API 响应 → 项目 raw schema 的确定性映射。

把 `/leagues/{id}/matchups` + `/markets/straight` 两个 API 响应转成符合
raw_payload.matches 结构的快照。映射规则经两轮抓取复盘验证
（docs/2026-06-29_morning_wc_run_log.md §3.1 / skill_execution_log.md §3.1）：

- main matchup（special 缺失）→ 1x2，prices 用 `designation` 字段映射 home/draw/away
- child（special.description 以 "3-Way Handicap" 开头）→ european_handicap，
  prices 无 designation，用 participant name 匹配主/客/Draw
- child（special.description == "Exact Total Goals"）→ exact_total_goals，
  用 participantId → participant.name 映射（name 即桶键如 "0"/"6+"）

本模块只做映射，不做赔率格式转换（保留美式整数，交由 normalization 层
american_to_decimal）也不做文件 I/O。
"""
from __future__ import annotations

import re
from typing import Any

DEFAULT_LEAGUE_ID = 2686
DEFAULT_URL = "https://www.pinnacle.com/en/soccer/fifa-world-cup/matchups/"


def matchups_to_raw(
    matchups: list[dict[str, Any]],
    markets: list[dict[str, Any]],
    *,
    fetched_at: str,
    league_id: int = DEFAULT_LEAGUE_ID,
    url: str = DEFAULT_URL,
) -> dict[str, Any]:
    """把 Pinnacle API 的 matchups + markets 转成 raw schema 快照。"""
    markets_by_matchup: dict[Any, list[dict[str, Any]]] = {}
    for market in markets:
        markets_by_matchup.setdefault(market.get("matchupId"), []).append(market)

    child_by_parent: dict[Any, list[dict[str, Any]]] = {}
    for matchup in matchups:
        parent = matchup.get("parent")
        if isinstance(parent, dict) and "id" in parent:
            child_by_parent.setdefault(parent["id"], []).append(matchup)

    out_matches: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for matchup in matchups:
        if not _is_main_matchup(matchup, league_id):
            continue
        home_name, away_name = _home_away_from_alignment(matchup.get("participants", []))
        if home_name is None or away_name is None:
            continue
        identity = (home_name, away_name, matchup.get("startTime"))
        if identity in seen:
            continue
        seen.add(identity)

        markets_out = _build_markets(
            matchup, home_name, away_name, markets_by_matchup, child_by_parent
        )
        if not markets_out:
            continue
        out_matches.append(
            {
                "source_match_id": str(matchup.get("id")),
                "home_team": home_name,
                "away_team": away_name,
                "start_time": matchup.get("startTime"),
                "markets": markets_out,
            }
        )

    return {
        "source": "pinnacle_browser",
        "url": url,
        "fetched_at": fetched_at,
        "odds_format": "american",
        "raw_payload": {"matches": out_matches},
    }


def _is_main_matchup(matchup: dict[str, Any], league_id: int) -> bool:
    """目标联赛的 main 3-way 对阵：special 缺失、participants==2、league 匹配。

    过滤 2-way 变体（Draw No Bet 等 special 非空）和 player props。
    """
    if matchup.get("special"):
        return False
    participants = matchup.get("participants") or []
    if len(participants) != 2:
        return False
    for participant in participants:
        name = participant.get("name", "")
        if name in {"Yes", "No", "Odd", "Even", "Over", "Under"}:
            return False
        if re.search(r"\([+-]?\d+\)|\b\d\+?$", name):
            return False
    return matchup.get("league", {}).get("id") == league_id


def _home_away_from_alignment(
    participants: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    home = next((p.get("name") for p in participants if p.get("alignment") == "home"), None)
    away = next((p.get("name") for p in participants if p.get("alignment") == "away"), None)
    if home is None and len(participants) >= 1:
        home = participants[0].get("name")
    if away is None and len(participants) >= 2:
        away = participants[1].get("name")
    return home, away


def _moneyline_prices(
    matchup_id: Any, markets_by_matchup: dict[Any, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    for market in markets_by_matchup.get(matchup_id, []):
        if market.get("type") == "moneyline" and market.get("period") == 0:
            return market.get("prices", []) or []
    return []


def _build_markets(
    matchup: dict[str, Any],
    home_name: str,
    away_name: str,
    markets_by_matchup: dict[Any, list[dict[str, Any]]],
    child_by_parent: dict[Any, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    markets_out: list[dict[str, Any]] = []

    odds_1x2 = _map_1x2_prices(_moneyline_prices(matchup.get("id"), markets_by_matchup))
    if odds_1x2:
        markets_out.append({"market_type": "1x2", "handicap": "", "odds": odds_1x2})

    for child in child_by_parent.get(matchup.get("id"), []):
        special = child.get("special") or {}
        description = special.get("description", "")
        prices = _moneyline_prices(child.get("id"), markets_by_matchup)
        child_participants = child.get("participants", [])
        if description.startswith("3-Way Handicap"):
            handicap_str = _handicap_from_description(description)
            if handicap_str is None:
                continue
            odds = _map_handicap_prices(prices, child_participants, home_name, away_name)
            if odds:
                markets_out.append(
                    {"market_type": "european_handicap", "handicap": handicap_str, "odds": odds}
                )
        elif description == "Exact Total Goals":
            odds = _map_total_goals_prices(prices, child_participants)
            if odds:
                markets_out.append(
                    {"market_type": "exact_total_goals", "handicap": "", "odds": odds}
                )

    return markets_out


def _map_1x2_prices(prices: list[dict[str, Any]]) -> dict[str, Any] | None:
    """main moneyline：必须用 designation 字段映射，缺失则跳过（禁止按位置猜）。

    复盘 2026-06-29 §3.1：按价格排序会把 favorite 误当 home，产生 +215% 假 EV。
    """
    by_designation = {
        price.get("designation"): price.get("price")
        for price in prices
        if price.get("designation")
    }
    if {"home", "draw", "away"}.issubset(by_designation.keys()):
        return {
            "home": by_designation["home"],
            "draw": by_designation["draw"],
            "away": by_designation["away"],
        }
    return None


def _handicap_from_description(description: str) -> str | None:
    """从 "3-Way Handicap Brazil -1" 末尾提取盘口 "+1"/"-1"。"""
    match = re.search(r"([+-]?\d+)\s*$", description)
    return match.group(1) if match else None


def _map_handicap_prices(
    prices: list[dict[str, Any]],
    child_participants: list[dict[str, Any]],
    home_name: str,
    away_name: str,
) -> dict[str, Any] | None:
    """3-Way Handicap child：prices 无 designation，用 participant name 匹配。

    名称形如 "Brazil (-1)" / "Draw - (Brazil -1)" / "Japan (+1)"。
    """
    pid_to_price = {price.get("participantId"): price.get("price") for price in prices}
    pid_to_name = {p["id"]: p.get("name", "") for p in child_participants if "id" in p}
    home_price = draw_price = away_price = None
    for pid, name in pid_to_name.items():
        price = pid_to_price.get(pid)
        if price is None:
            continue
        base_name = name.split("(")[0].strip()
        if name.startswith("Draw"):
            draw_price = price
        elif base_name == home_name:
            home_price = price
        elif base_name == away_name:
            away_price = price
    if None in (home_price, draw_price, away_price):
        return None
    return {"home": home_price, "draw": draw_price, "away": away_price}


def _map_total_goals_prices(
    prices: list[dict[str, Any]], child_participants: list[dict[str, Any]]
) -> dict[str, Any]:
    """Exact Total Goals child：participantId → participant.name 直接映射。

    name 即桶键（"0"/"1"/.../"6+"）。
    """
    pid_to_name = {p["id"]: p.get("name", "") for p in child_participants if "id" in p}
    return {
        pid_to_name[price["participantId"]]: price["price"]
        for price in prices
        if price.get("participantId") in pid_to_name
    }
