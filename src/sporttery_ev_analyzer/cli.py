from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .analysis import analyze, render_markdown
from .io_utils import read_json, write_json
from .normalization import normalize_pair


def main() -> None:
    parser = argparse.ArgumentParser(prog="sporttery-ev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize", help="normalize two raw JSON snapshots")
    normalize_parser.add_argument("--sporttery-raw", required=True, nargs="+")
    normalize_parser.add_argument("--market-raw", required=True, nargs="+")
    normalize_parser.add_argument("--output", required=True)
    normalize_parser.add_argument("--max-start-delta-minutes", type=int, default=30)
    normalize_parser.add_argument("--team-aliases")

    analyze_parser = subparsers.add_parser("analyze", help="generate JSON and Markdown EV reports")
    analyze_parser.add_argument("--normalized", required=True)
    analyze_parser.add_argument("--json-output", required=True)
    analyze_parser.add_argument("--md-output", required=True)
    analyze_parser.add_argument("--ev-threshold", type=float, default=0.0)
    analyze_parser.add_argument("--combo-ev-threshold", type=float, default=0.08)
    analyze_parser.add_argument("--kelly-fraction", type=float, default=0.1)
    analyze_parser.add_argument("--max-source-delta-minutes", type=int, default=180)
    analyze_parser.add_argument("--max-data-age-minutes", type=int, default=240)

    fetch_parser = subparsers.add_parser("fetch-browser", help="safe placeholder for manual low-frequency browser capture")
    fetch_parser.add_argument("--source", required=True, choices=["sporttery_browser", "pinnacle_browser"])
    fetch_parser.add_argument("--url", required=True)
    fetch_parser.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "normalize":
        normalized = normalize_pair(
            merge_raw_files([read_json(path) for path in args.sporttery_raw]),
            merge_raw_files([read_json(path) for path in args.market_raw]),
            max_start_delta_minutes=args.max_start_delta_minutes,
            team_aliases=read_json(args.team_aliases) if args.team_aliases else None,
        )
        write_json(args.output, normalized)
        return

    if args.command == "analyze":
        report = analyze(
            read_json(args.normalized),
            ev_threshold=args.ev_threshold,
            combo_ev_threshold=args.combo_ev_threshold,
            kelly_fraction=args.kelly_fraction,
            max_source_delta_minutes=args.max_source_delta_minutes,
            max_data_age_minutes=args.max_data_age_minutes,
        )
        write_json(args.json_output, report)
        md_path = Path(args.md_output)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(report), encoding="utf-8")
        return

    raise SystemExit(
        "fetch-browser is a safe manual capture placeholder. Open the official Sporttery or Pinnacle page in a normal browser, "
        "do not bypass login/captcha/geo restrictions, and save a raw JSON snapshot with source/url/fetched_at/raw_payload. "
        "This command does not scrape or generate a calculable snapshot automatically."
    )


def _match_identity(match: dict[str, Any]) -> tuple:
    """返回比赛身份键，用于合并多份 raw 中同一场比赛的不同玩法市场。

    优先用 source_match_id（同源快照稳定 ID）；缺失时回退球队名+start_time 三元组。
    """
    source_id = match.get("source_match_id")
    if source_id:
        return ("id", str(source_id))
    return (
        "teams",
        str(match.get("home_team", "")),
        str(match.get("away_team", "")),
        str(match.get("start_time", "")),
    )


def merge_raw_files(raws: list[dict[str, Any]]) -> dict[str, Any]:
    """把多份同源 raw 快照合并成一份，供 normalize_pair 使用。

    had/hhad 与 ttg 在 Sporttery 不同页面，分页抓取后无需外部脚本即可直接传入。
    source 和 odds_format 必须在所有份中一致；fetched_at 取最早一份以保证时效校验保守。
    """
    if not raws:
        raise ValueError("at least one raw snapshot is required")
    if len(raws) == 1:
        return raws[0]

    first = raws[0]
    source = first.get("source")
    odds_format = first.get("odds_format")
    for raw in raws[1:]:
        if raw.get("source") != source:
            raise ValueError(f"cannot merge raws with different sources: {source} vs {raw.get('source')}")
        if raw.get("odds_format") != odds_format:
            raise ValueError(f"cannot merge raws with different odds_format: {odds_format} vs {raw.get('odds_format')}")

    # 按比赛身份合并 markets 进同一行，避免产生重复行触发 normalize_pair 的
    # used_market_indexes 锁死（复盘 2026-06-29 §3.3 / Gemini 报告 §3.1）。
    # 优先用 source_match_id（同源快照稳定 ID）；缺失时回退球队+start_time 三元组。
    merged_matches: list[dict[str, Any]] = []
    by_identity: dict[tuple, int] = {}
    for raw in raws:
        payload = raw.get("raw_payload", raw)
        matches = payload.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            identity = _match_identity(match)
            if identity in by_identity:
                target = merged_matches[by_identity[identity]]
                target.setdefault("markets", []).extend(match.get("markets", []))
            else:
                by_identity[identity] = len(merged_matches)
                merged_matches.append(dict(match))

    # fetched_at 取最早一份，保证下游时效性校验保守
    fetched_values = [raw.get("fetched_at") for raw in raws if raw.get("fetched_at")]
    fetched_at = min(fetched_values) if fetched_values else first.get("fetched_at")

    merged: dict[str, Any] = dict(first)
    merged["fetched_at"] = fetched_at
    merged["raw_payload"] = {"matches": merged_matches}
    return merged


if __name__ == "__main__":
    main()
