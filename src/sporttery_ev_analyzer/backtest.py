from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import parse_iso_datetime, read_json, utc_now_iso
from .normalization import _build_alias_lookup, _canon_team

DEFAULT_THRESHOLDS = (-0.05, -0.025)


def backtest(
    reports_dir: str | Path,
    results_path: str | Path,
    *,
    rerun_dir: str | Path | None = None,
    team_aliases: dict[str, list[str]] | None = None,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    excluded_market_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    generated_at = utc_now_iso()
    reports_dir = Path(reports_dir)
    rerun_dir = Path(rerun_dir) if rerun_dir else reports_dir / "rerun_shin_power"
    alias_lookup = _build_alias_lookup(team_aliases or {})
    results = _load_results(results_path, alias_lookup)
    main_reports = _load_reports(reports_dir.glob("*_ev_report.json"))
    rerun_reports = {path.name: report for path, report in _load_reports(rerun_dir.glob("*_ev_report.json"))}

    proportional_bets, unsettled = _collect_bets(main_reports, results, alias_lookup, "proportional")
    proportional_bets = _exclude_market_types(proportional_bets, excluded_market_types)
    method_accuracy = {}
    for method in ("shin", "power"):
        method_reports = [(path, rerun_reports.get(path.name, report)) for path, report in main_reports]
        method_bets, method_unsettled = _collect_bets(method_reports, results, alias_lookup, method)
        method_bets = _exclude_market_types(method_bets, excluded_market_types)
        method_accuracy[method] = _method_accuracy(method_bets, method_unsettled, thresholds)

    return {
        "generated_at": generated_at,
        "parameters": {
            "reports_dir": str(reports_dir),
            "results_path": str(results_path),
            "rerun_dir": str(rerun_dir),
            "thresholds": list(thresholds),
            "excluded_market_types": list(excluded_market_types),
            "stake_per_bet": 1.0,
            "bet_type": "single_equal_stake",
        },
        "results_source": {
            "path": str(results_path),
            "ft_matches": len(results),
        },
        "summary": {
            _threshold_label(threshold): {
                "rolling": _summarize(_rolling_bets(proportional_bets, threshold)),
                "closing": _summarize(_closing_bets(proportional_bets, threshold)),
            }
            for threshold in thresholds
        },
        "selected_bets": {
            _threshold_label(threshold): {
                "rolling": _rolling_bets(proportional_bets, threshold),
                "closing": _closing_bets(proportional_bets, threshold),
            }
            for threshold in thresholds
        },
        "method_accuracy": method_accuracy,
        "bets": proportional_bets,
        "unsettled": unsettled,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 历史 EV 回测",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 比分文件：{report['parameters']['results_path']}",
        f"- 已载入完赛比分：{report['results_source']['ft_matches']}",
        "- 投注口径：滚动投注每场每快照最多 1 注；临场投注每场最多 1 注；每注等额 1 单位；不含串关、不含自动下注",
        "",
        "## 比例 EV 回测",
        "",
        "| 策略 | 口径 | 投注项数 | 比赛场数 | 命中投注项 | 命中比赛数 | 成功率 | 总投入 | 总返还 | 净收益 | ROI |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for threshold, scopes in report["summary"].items():
        for scope_name, summary in scopes.items():
            lines.append(_summary_row(threshold, _scope_label(scope_name), summary))

    lines.extend(["", "## 投注场次列表", ""])
    for threshold, scopes in report["summary"].items():
        for scope_name, summary in scopes.items():
            lines.extend([f"### {threshold} / {_scope_label(scope_name)}", ""])
            _append_match_table(lines, summary["matches"], empty_text="无投注场次。")

    lines.extend(["", "## 命中比赛", ""])
    for threshold, scopes in report["summary"].items():
        for scope_name, summary in scopes.items():
            lines.extend([f"### {threshold} / {_scope_label(scope_name)}", ""])
            _append_match_table(lines, summary["winning_matches"], empty_text="无命中比赛。", wins_only=True)

    lines.extend(
        [
            "",
            "## ShinEV / 指数EV 命中率",
            "",
            "| 方法 | 策略 | 口径 | 投注项数 | 比赛场数 | 命中投注项 | 命中比赛数 | 成功率 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for method, thresholds in report["method_accuracy"].items():
        for threshold, scopes in thresholds.items():
            for scope_name, summary in scopes.items():
                if scope_name == "unsettled":
                    continue
                lines.append(
                    f"| {method} | {threshold} | {_scope_label(scope_name)} | {summary['bets']} | "
                    f"{summary['match_count']} | {summary['wins']} | {summary['winning_match_count']} | "
                    f"{_format_percent(summary['success_rate'])} |"
                )

    lines.extend(
        [
            "",
            "## 未结算",
            "",
            f"- 未结算投注行：{len(report.get('unsettled', []))}",
            "- 原因包括比分缺失、非 FT、队名无法匹配或玩法无法结算；这些行不进入成功率和 ROI 分母。",
            "",
        ]
    )
    return "\n".join(lines)


def _load_reports(paths) -> list[tuple[Path, dict[str, Any]]]:
    reports = []
    for path in sorted(paths):
        report = read_json(path)
        if report.get("report_status") == "ok":
            reports.append((path, report))
    return reports


def _load_results(path: str | Path, alias_lookup: dict[str, str]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_json(path)
    results = {}
    for row in rows:
        if row.get("status") != "FT":
            continue
        try:
            home_score = int(row["homeScore"])
            away_score = int(row["awayScore"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (_canon_team(row.get("homeTeam"), alias_lookup), _canon_team(row.get("awayTeam"), alias_lookup))
        results[key] = {
            "home_score": home_score,
            "away_score": away_score,
            "source": row,
        }
    return results


def _collect_bets(
    reports: list[tuple[Path, dict[str, Any]]],
    results: dict[tuple[str, str], dict[str, Any]],
    alias_lookup: dict[str, str],
    method: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bets = []
    unsettled = []
    for path, report in reports:
        snapshot_at = _snapshot_at(path, report)
        for row in report.get("single_ev", []):
            ev = _row_ev(row, method)
            if ev is None:
                continue
            key = (_canon_team(row.get("home_team"), alias_lookup), _canon_team(row.get("away_team"), alias_lookup))
            result = results.get(key)
            base = {
                "report_file": str(path),
                "snapshot_at": snapshot_at,
                "method": method,
                "canonical_match_key": "|".join(key),
                "match_id": row.get("match_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "start_time": row.get("start_time"),
                "market_type": row.get("market_type"),
                "handicap": row.get("handicap"),
                "outcome": row.get("outcome"),
                "sporttery_odds": row.get("sporttery_odds"),
                "ev": ev,
            }
            if result is None:
                unsettled.append({**base, "reason": "missing_ft_result"})
                continue
            outcome = _settled_outcome(row, result["home_score"], result["away_score"])
            if outcome is None:
                unsettled.append({**base, "reason": "unsupported_market_or_outcome"})
                continue
            win = row.get("outcome") == outcome
            odds = float(row["sporttery_odds"])
            bets.append(
                {
                    **base,
                    "home_score": result["home_score"],
                    "away_score": result["away_score"],
                    "settled_outcome": outcome,
                    "win": win,
                    "stake": 1.0,
                    "return": odds if win else 0.0,
                    "profit": odds - 1.0 if win else -1.0,
                }
            )
    return bets, unsettled


def _row_ev(row: dict[str, Any], method: str) -> float | None:
    if method == "proportional":
        return float(row["single_ev"])
    comparison = row.get("method_comparison", {}).get(method, {})
    if comparison.get("status") != "ok" or "single_ev" not in comparison:
        return None
    return float(comparison["single_ev"])


def _snapshot_at(path: Path, report: dict[str, Any]) -> str:
    fetched = [
        value
        for value in (
            report.get("inputs", {}).get("sporttery", {}).get("fetched_at"),
            report.get("inputs", {}).get("market", {}).get("fetched_at"),
        )
        if value
    ]
    if fetched:
        return parse_iso_datetime(str(max(fetched, key=lambda value: parse_iso_datetime(str(value))))).isoformat()
    try:
        stem = path.name.removesuffix("_ev_report.json")
        return datetime.strptime(stem, "%Y-%m-%d_%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return str(report.get("generated_at") or path.stat().st_mtime)


def _settled_outcome(row: dict[str, Any], home_score: int, away_score: int) -> str | None:
    market_type = row.get("market_type")
    if market_type == "1x2":
        return _three_way(home_score, away_score)
    if market_type == "handicap_3way":
        try:
            adjusted_home = home_score + float(row.get("handicap") or 0)
        except (TypeError, ValueError):
            return None
        return _three_way(adjusted_home, away_score)
    if market_type == "total_goals":
        total = home_score + away_score
        outcome = str(row.get("outcome"))
        if outcome.endswith("+"):
            try:
                return outcome if total >= int(outcome[:-1]) else str(total)
            except ValueError:
                return None
        return str(total)
    return None


def _three_way(home_value: float, away_value: float) -> str:
    if home_value > away_value:
        return "home"
    if home_value < away_value:
        return "away"
    return "draw"


def _filter_bets(bets: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return [bet for bet in bets if bet["ev"] >= threshold]


def _exclude_market_types(bets: list[dict[str, Any]], market_types: tuple[str, ...]) -> list[dict[str, Any]]:
    excluded = set(market_types)
    if not excluded:
        return bets
    return [bet for bet in bets if bet.get("market_type") not in excluded]


def _rolling_bets(bets: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return _filter_bets(bets, threshold)


def _closing_bets(bets: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return _latest_outcome_bets(_filter_bets(bets, threshold))


def _match_key(bet: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (bet.get("canonical_match_key"),)


def _summarize(bets: list[dict[str, Any]]) -> dict[str, Any]:
    stake = sum(bet["stake"] for bet in bets)
    returned = sum(bet["return"] for bet in bets)
    profit = returned - stake
    wins = sum(1 for bet in bets if bet["win"])
    count = len(bets)
    matches = _match_groups(bets)
    winning_matches = _match_groups([bet for bet in bets if bet["win"]])
    return {
        "bets": count,
        "wins": wins,
        "match_count": len(matches),
        "winning_match_count": len(winning_matches),
        "success_rate": wins / count if count else None,
        "stake": stake,
        "return": returned,
        "profit": profit,
        "roi": profit / stake if stake else None,
        "matches": matches,
        "winning_matches": winning_matches,
    }


def _match_groups(bets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for bet in bets:
        grouped.setdefault(str(bet.get("canonical_match_key")), []).append(bet)

    rows = []
    for key, items in grouped.items():
        latest = max(items, key=lambda item: parse_iso_datetime(item["snapshot_at"]))
        wins = [item for item in items if item["win"]]
        rows.append(
            {
                "canonical_match_key": key,
                "snapshot_at": latest["snapshot_at"],
                "match": f"{latest['home_team']} vs {latest['away_team']}",
                "score": f"{latest['home_score']}-{latest['away_score']}",
                "bet_count": len(items),
                "win_count": len(wins),
                "profit": sum(float(item["profit"]) for item in items),
                "options": _option_summary(items),
                "winning_options": _option_summary(wins),
            }
        )
    return sorted(rows, key=lambda row: (row["snapshot_at"], row["match"]))


def _option_summary(bets: list[dict[str, Any]]) -> str:
    if not bets:
        return ""
    parts = []
    for bet in sorted(bets, key=lambda item: (item["market_type"], str(item.get("handicap") or ""), item["outcome"], item["snapshot_at"])):
        handicap = f" {bet.get('handicap')}" if bet.get("handicap") else ""
        parts.append(f"{bet['market_type']}{handicap} {bet['outcome']}({float(bet['ev']) * 100:.2f}%)")
    return "; ".join(parts)


def _method_accuracy(
    bets: list[dict[str, Any]],
    unsettled: list[dict[str, Any]],
    thresholds: tuple[float, ...],
) -> dict[str, Any]:
    return {
        _threshold_label(threshold): {
            "rolling": _accuracy(_filter_bets(bets, threshold)),
            "closing": _accuracy(_latest_outcome_bets(_filter_bets(bets, threshold))),
            "unsettled": len([row for row in unsettled if row["ev"] >= threshold]),
        }
        for threshold in thresholds
    }


def _latest_outcome_bets(bets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = {}
    for bet in bets:
        key = (
            _match_key(bet),
            bet["market_type"],
            str(bet.get("handicap") or ""),
            bet["outcome"],
        )
        if key not in latest or parse_iso_datetime(bet["snapshot_at"]) > parse_iso_datetime(latest[key]["snapshot_at"]):
            latest[key] = bet
    return list(latest.values())


def _accuracy(bets: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize(bets)
    return {
        "bets": summary["bets"],
        "wins": summary["wins"],
        "match_count": summary["match_count"],
        "winning_match_count": summary["winning_match_count"],
        "success_rate": summary["success_rate"],
    }


def _threshold_label(threshold: float) -> str:
    return f"EV >= {threshold * 100:.1f}%"


def _scope_label(scope: str) -> str:
    return {"rolling": "滚动投注", "closing": "临场投注"}[scope]


def _summary_row(threshold: str, scope: str, summary: dict[str, Any]) -> str:
    return (
        f"| {threshold} | {scope} | {summary['bets']} | {summary['match_count']} | "
        f"{summary['wins']} | {summary['winning_match_count']} | {_format_percent(summary['success_rate'])} | {summary['stake']:.2f} | "
        f"{summary['return']:.2f} | {summary['profit']:.2f} | {_format_percent(summary['roi'])} |"
    )


def _append_match_table(lines: list[str], matches: list[dict[str, Any]], *, empty_text: str, wins_only: bool = False) -> None:
    if not matches:
        lines.extend([empty_text, ""])
        return
    option_header = "命中选项" if wins_only else "入选选项"
    lines.append(f"| 快照时间 | 比赛 | 比分 | 投注项数 | 命中项数 | 收益 | {option_header} |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | --- |")
    for match in matches:
        options = match["winning_options"] if wins_only else match["options"]
        lines.append(
            f"| {match['snapshot_at']} | {match['match']} | {match['score']} | {match['bet_count']} | "
            f"{match['win_count']} | {float(match['profit']):.2f} | {options} |"
        )
    lines.append("")


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"
