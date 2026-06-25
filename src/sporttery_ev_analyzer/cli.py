from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import analyze, render_markdown
from .io_utils import read_json, write_json
from .normalization import normalize_pair


def main() -> None:
    parser = argparse.ArgumentParser(prog="sporttery-ev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize", help="normalize two raw JSON snapshots")
    normalize_parser.add_argument("--sporttery-raw", required=True)
    normalize_parser.add_argument("--market-raw", required=True)
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
            read_json(args.sporttery_raw),
            read_json(args.market_raw),
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


if __name__ == "__main__":
    main()
