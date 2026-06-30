import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sporttery_ev_analyzer.backtest import backtest, render_markdown


def _row(match_id, home, away, market_type, outcome, ev, odds=2.0, handicap=""):
    return {
        "match_id": match_id,
        "home_team": home,
        "away_team": away,
        "start_time": "2026-06-25T12:00:00+00:00",
        "market_type": market_type,
        "handicap": handicap,
        "outcome": outcome,
        "sporttery_odds": odds,
        "single_ev": ev,
        "method_comparison": {
            "shin": {"status": "ok", "single_ev": ev - 0.01},
            "power": {"status": "ok", "single_ev": ev + 0.01},
        },
    }


def _report(fetched_at, rows):
    return {
        "report_status": "ok",
        "inputs": {
            "sporttery": {"fetched_at": fetched_at},
            "market": {"fetched_at": fetched_at},
        },
        "single_ev": rows,
    }


class BacktestTests(unittest.TestCase):
    def test_settles_markets_thresholds_and_closing_snapshot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "analysis"
            reports.mkdir()
            results = root / "results.json"
            results.write_text(
                json.dumps(
                    [
                        {"homeTeam": "Alpha", "awayTeam": "Beta", "homeScore": 2, "awayScore": 1, "status": "FT"},
                        {"homeTeam": "Gamma", "awayTeam": "Delta", "homeScore": 1, "awayScore": 1, "status": "FT"},
                        {"homeTeam": "Total", "awayTeam": "Goals", "homeScore": 4, "awayScore": 3, "status": "FT"},
                    ]
                ),
                encoding="utf-8",
            )
            aliases = {
                "alpha": ["Alpha"],
                "beta": ["Beta"],
                "gamma": ["Gamma"],
                "delta": ["Delta"],
                "total": ["Total"],
                "goals": ["Goals"],
                "missing": ["Missing"],
                "team": ["Team"],
            }
            first_rows = [
                _row("A", "Alpha", "Beta", "1x2", "home", -0.05, odds=2.2),
                _row("G", "Gamma", "Delta", "handicap_3way", "home", -0.024, handicap="+1"),
                _row("T", "Total", "Goals", "total_goals", "7+", -0.03, odds=3.5),
                _row("M", "Missing", "Team", "1x2", "home", 0.2),
            ]
            second_rows = [_row("A", "Alpha", "Beta", "1x2", "home", -0.01, odds=1.5)]
            (reports / "2026-06-25_100000_ev_report.json").write_text(json.dumps(_report("2026-06-25T10:00:00+00:00", first_rows)), encoding="utf-8")
            (reports / "2026-06-25_110000_ev_report.json").write_text(json.dumps(_report("2026-06-25T11:00:00+00:00", second_rows)), encoding="utf-8")

            output = backtest(reports, results, team_aliases=aliases)

        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["bets"], 4)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["match_count"], 3)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["wins"], 4)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["winning_match_count"], 3)
        self.assertAlmostEqual(output["summary"]["EV >= -5.0%"]["rolling"]["profit"], 5.2)
        self.assertEqual(output["summary"]["EV >= -2.5%"]["rolling"]["bets"], 2)
        self.assertEqual(output["summary"]["EV >= -2.5%"]["rolling"]["wins"], 2)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["bets"], 3)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["match_count"], 3)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["wins"], 3)
        self.assertEqual(len(output["unsettled"]), 1)
        markdown = render_markdown(output)
        self.assertIn("## 投注场次列表", markdown)
        self.assertIn("## 命中比赛", markdown)
        self.assertIn("Alpha vs Beta", markdown)
        self.assertIn("| 2026-06-25T11:00:00+00:00 | Alpha vs Beta | 2-1 | 2 | 2 |", markdown)
        self.assertIn("| 2026-06-25T10:00:00+00:00 | Total vs Goals | 4-3 | 1 | 1 |", markdown)

    def test_shin_and_power_accuracy_are_separate_from_main_roi(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "analysis"
            rerun = reports / "rerun_shin_power"
            rerun.mkdir(parents=True)
            results = root / "results.json"
            results.write_text(
                json.dumps([{"homeTeam": "Alpha", "awayTeam": "Beta", "homeScore": 2, "awayScore": 0, "status": "FT"}]),
                encoding="utf-8",
            )
            aliases = {"alpha": ["Alpha"], "beta": ["Beta"]}
            original = _report("2026-06-25T10:00:00+00:00", [_row("A", "Alpha", "Beta", "1x2", "home", -0.06)])
            rerun_report = _report("2026-06-25T10:00:00+00:00", [_row("A", "Alpha", "Beta", "1x2", "home", -0.06)])
            rerun_report["single_ev"][0]["method_comparison"]["shin"]["single_ev"] = -0.04
            rerun_report["single_ev"][0]["method_comparison"]["power"]["single_ev"] = -0.06
            (reports / "2026-06-25_100000_ev_report.json").write_text(json.dumps(original), encoding="utf-8")
            (rerun / "2026-06-25_100000_ev_report.json").write_text(json.dumps(rerun_report), encoding="utf-8")

            output = backtest(reports, results, rerun_dir=rerun, team_aliases=aliases)

        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["bets"], 0)
        self.assertEqual(output["method_accuracy"]["shin"]["EV >= -5.0%"]["rolling"]["bets"], 1)
        self.assertEqual(output["method_accuracy"]["power"]["EV >= -5.0%"]["rolling"]["bets"], 0)

    def test_closing_uses_canonical_team_names_for_same_match(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "analysis"
            reports.mkdir()
            results = root / "results.json"
            results.write_text(
                json.dumps([{"homeTeam": "DR Congo", "awayTeam": "Uzbekistan", "homeScore": 3, "awayScore": 1, "status": "FT"}]),
                encoding="utf-8",
            )
            aliases = {
                "dr_congo": ["DR Congo", "刚果(金)", "刚果金"],
                "uzbekistan": ["Uzbekistan", "乌兹别克斯坦", "乌兹别克"],
            }
            first = _report("2026-06-25T10:00:00+00:00", [_row("X1", "刚果(金)", "乌兹别克斯坦", "1x2", "home", -0.01)])
            second = _report("2026-06-25T11:00:00+00:00", [_row("X2", "刚果金", "乌兹别克", "1x2", "home", 0.02)])
            (reports / "2026-06-25_100000_ev_report.json").write_text(json.dumps(first), encoding="utf-8")
            (reports / "2026-06-25_110000_ev_report.json").write_text(json.dumps(second), encoding="utf-8")

            output = backtest(reports, results, team_aliases=aliases)

        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["bets"], 2)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["rolling"]["match_count"], 1)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["bets"], 1)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["match_count"], 1)
        self.assertEqual(output["summary"]["EV >= -5.0%"]["closing"]["matches"][0]["match"], "刚果金 vs 乌兹别克")

    def test_closing_keeps_all_in_range_outcomes_for_same_match(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "analysis"
            reports.mkdir()
            results = root / "results.json"
            results.write_text(
                json.dumps([{"homeTeam": "Germany", "awayTeam": "Paraguay", "homeScore": 1, "awayScore": 1, "status": "FT"}]),
                encoding="utf-8",
            )
            aliases = {"germany": ["Germany", "德国"], "paraguay": ["Paraguay", "巴拉圭"]}
            report = _report(
                "2026-06-25T11:00:00+00:00",
                [
                    _row("G", "德国", "巴拉圭", "handicap_3way", "draw", 0.028, odds=4.05, handicap="-1"),
                    _row("G", "德国", "巴拉圭", "handicap_3way", "away", 0.0075, odds=3.44, handicap="-1"),
                ],
            )
            (reports / "2026-06-25_110000_ev_report.json").write_text(json.dumps(report), encoding="utf-8")

            output = backtest(reports, results, team_aliases=aliases)

        closing = output["summary"]["EV >= -5.0%"]["closing"]
        self.assertEqual(closing["bets"], 2)
        self.assertEqual(closing["match_count"], 1)
        self.assertEqual(closing["wins"], 1)
        self.assertEqual(closing["matches"][0]["options"], "handicap_3way -1 away(0.75%); handicap_3way -1 draw(2.80%)")
        self.assertEqual(closing["winning_matches"][0]["winning_options"], "handicap_3way -1 away(0.75%)")

    def test_excluded_market_types_do_not_count_as_bets(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "analysis"
            reports.mkdir()
            results = root / "results.json"
            results.write_text(
                json.dumps([{"homeTeam": "Alpha", "awayTeam": "Beta", "homeScore": 0, "awayScore": 0, "status": "FT"}]),
                encoding="utf-8",
            )
            aliases = {"alpha": ["Alpha"], "beta": ["Beta"]}
            report = _report(
                "2026-06-25T11:00:00+00:00",
                [
                    _row("A", "Alpha", "Beta", "total_goals", "0", 0.2, odds=8.0),
                    _row("A", "Alpha", "Beta", "1x2", "draw", -0.01, odds=3.0),
                ],
            )
            (reports / "2026-06-25_110000_ev_report.json").write_text(json.dumps(report), encoding="utf-8")

            output = backtest(reports, results, team_aliases=aliases, excluded_market_types=("total_goals",))

        closing = output["summary"]["EV >= -5.0%"]["closing"]
        self.assertEqual(closing["bets"], 1)
        self.assertEqual(closing["wins"], 1)
        self.assertEqual(closing["matches"][0]["options"], "1x2 draw(-1.00%)")


if __name__ == "__main__":
    unittest.main()
