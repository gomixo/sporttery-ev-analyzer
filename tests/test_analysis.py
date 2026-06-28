import unittest

from sporttery_ev_analyzer.analysis import analyze, render_markdown


def _normalized():
    return {
        "generated_at": "2026-06-25T10:03:00+00:00",
        "inputs": {
            "sporttery": {"source": "sporttery", "fetched_at": "2026-06-25T10:00:00+00:00"},
            "market": {"source": "pinnacle", "fetched_at": "2026-06-25T10:02:00+00:00"},
        },
        "matches": [
            {
                "match_id": "M001",
                "home_team": "Alpha FC",
                "away_team": "Beta United",
                "start_time": "2026-06-25T12:00:00+00:00",
                "market_type": "1x2",
                "handicap": "",
                "matched_status": "matched",
                "match_confidence": 1.0,
                "sporttery": {"odds": {"home": 2.15, "draw": 3.2, "away": 3.1}},
                "market": {"odds": {"home": 1.9, "draw": 3.45, "away": 4.2}},
            },
            {
                "match_id": "M002",
                "home_team": "Gamma City",
                "away_team": "Delta Town",
                "start_time": "2026-06-25T13:00:00+00:00",
                "market_type": "1x2",
                "handicap": "",
                "matched_status": "matched",
                "match_confidence": 1.0,
                "sporttery": {"odds": {"home": 2.25, "draw": 3.25, "away": 3.4}},
                "market": {"odds": {"home": 1.95, "draw": 3.4, "away": 4.0}},
            },
        ],
        "unmatched": [],
    }


class AnalysisTests(unittest.TestCase):
    def test_analyze_builds_only_cross_match_positive_ev_combos(self):
        report = analyze(_normalized(), combo_ev_threshold=0.08, max_data_age_minutes=1000000)

        self.assertEqual(report["report_status"], "ok")
        self.assertTrue(all(item["single_ev"] > 0 for item in report["positive_single_ev"]))
        self.assertTrue(report["combo_candidates"])
        self.assertTrue(all(combo["legs"][0]["match_id"] != combo["legs"][1]["match_id"] for combo in report["combo_candidates"]))
        self.assertTrue(all(leg["single_ev"] > 0 for combo in report["combo_candidates"] for leg in combo["legs"]))

    def test_analyze_includes_advanced_method_comparison_without_changing_primary_fields(self):
        report = analyze(_normalized(), combo_ev_threshold=0.08, max_data_age_minutes=1000000)
        first = report["single_ev"][0]

        self.assertEqual(round(first["fair_probability"], 6), 0.499225)
        self.assertEqual(first["method_comparison"]["proportional"]["status"], "ok")
        self.assertEqual(first["method_comparison"]["shin"]["status"], "ok")
        self.assertEqual(first["method_comparison"]["power"]["status"], "ok")
        self.assertEqual(round(first["method_comparison"]["shin"]["fair_probability"], 6), 0.505907)
        self.assertEqual(round(first["method_comparison"]["power"]["fair_probability"], 6), 0.508442)

    def test_analyze_blocks_when_source_time_delta_is_too_large(self):
        normalized = _normalized()
        normalized["inputs"]["market"]["fetched_at"] = "2026-06-25T14:30:00+00:00"

        report = analyze(normalized, max_source_delta_minutes=180, max_data_age_minutes=1000000)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["single_ev"], [])
        self.assertEqual(report["combo_candidates"], [])
        self.assertEqual(report["freshness"]["reason"], "source_time_delta_too_large")

    def test_single_positive_candidate_does_not_force_pairing(self):
        normalized = _normalized()
        normalized["matches"] = normalized["matches"][:1]

        report = analyze(normalized, max_data_age_minutes=1000000)

        self.assertTrue(report["positive_single_ev"])
        self.assertEqual(report["combo_candidates"], [])
        self.assertEqual(report["conclusion"], "无法配对，建议空仓")

    def test_negative_ev_threshold_does_not_admit_non_positive_combo_leg(self):
        normalized = _normalized()
        normalized["matches"][0]["sporttery"]["odds"]["home"] = 1.98

        report = analyze(
            normalized,
            ev_threshold=-0.05,
            combo_ev_threshold=0.0,
            max_data_age_minutes=1000000,
        )

        self.assertTrue(normalized["matches"][0]["match_id"] not in {item["match_id"] for item in report["positive_single_ev"]})
        self.assertEqual(report["combo_candidates"], [])

    def test_analyze_blocks_when_data_age_is_too_large(self):
        normalized = _normalized()

        report = analyze(normalized, max_data_age_minutes=1)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["single_ev"], [])
        self.assertEqual(report["combo_candidates"], [])
        self.assertEqual(report["freshness"]["reason"], "data_age_too_large")
        self.assertEqual(report["parameters"]["max_data_age_minutes"], 1)

    def test_invalid_odds_are_reported_as_data_quality_warnings(self):
        normalized = _normalized()
        normalized["matches"] = [
            {
                "match_id": "M003",
                "home_team": "Korea Republic",
                "away_team": "Japan",
                "start_time": "2026-06-25T12:00:00+00:00",
                "market_type": "1x2",
                "handicap": "",
                "matched_status": "matched",
                "match_confidence": 1.0,
                "sporttery": {"odds": {"home": "-", "draw": 3.0, "away": 3.5}},
                "market": {"odds": {"home": 1.9, "draw": 3.2, "away": 4.0}},
            },
            {
                "match_id": "M004",
                "home_team": "Brazil",
                "away_team": "Germany",
                "start_time": "2026-06-25T13:00:00+00:00",
                "market_type": "1x2",
                "handicap": "",
                "matched_status": "matched",
                "match_confidence": 1.0,
                "sporttery": {"odds": {"home": 0, "draw": 3.0, "away": 3.5}},
                "market": {"odds": {"home": 1.9, "draw": 3.2, "away": 4.0}},
            },
        ]

        report = analyze(normalized, max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["combo_candidates"], [])
        self.assertEqual(report["single_ev"], [])
        self.assertEqual(len(report["skipped"]), 2)
        self.assertEqual(len(report["data_quality_warnings"]), 2)
        self.assertIn("数据质量警告", markdown)
        self.assertEqual(report["conclusion"], "没有可计算的 EV 明细，停止分析，建议空仓并人工复核。")

    def test_non_pinnacle_market_source_blocks_report(self):
        normalized = _normalized()
        normalized["inputs"]["market"]["source"] = "polymarket"

        report = analyze(normalized, max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["single_ev"], [])
        self.assertFalse(report["source_validation"]["is_usable"])
        self.assertIn("market source must be one of", markdown)

    def test_non_official_sporttery_source_blocks_report(self):
        normalized = _normalized()
        normalized["inputs"]["sporttery"]["source"] = "500"

        report = analyze(normalized, max_data_age_minutes=1000000)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["combo_candidates"], [])
        self.assertFalse(report["source_validation"]["is_usable"])

    def test_analyze_does_not_trust_forged_source_validation(self):
        normalized = _normalized()
        normalized["inputs"]["market"]["source"] = "polymarket"
        normalized["source_validation"] = {"is_usable": True, "errors": []}

        report = analyze(normalized, max_data_age_minutes=1000000)

        self.assertEqual(report["report_status"], "blocked")
        self.assertFalse(report["source_validation"]["is_usable"])
        self.assertTrue(report["source_validation"]["errors"])

    def test_analyze_blocks_when_no_matches_are_calculable(self):
        normalized = _normalized()
        normalized["matches"] = []

        report = analyze(normalized, max_data_age_minutes=1000000)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["conclusion"], "没有可计算的匹配赛事，停止分析，建议空仓并人工复核。")

    def test_markdown_outputs_all_ev_rows_not_only_positive_rows(self):
        report = analyze(_normalized(), max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertIn("全部 EV 对比明细", markdown)
        self.assertIn("Beta United", markdown)
        self.assertIn("-12.02%", markdown)

    def test_markdown_outputs_ev_as_percent(self):
        report = analyze(_normalized(), max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertIn("7.33%", markdown)
        self.assertNotIn("0.0733", markdown)

    def test_markdown_outputs_three_margin_methods_and_primary_label(self):
        report = analyze(_normalized(), max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertIn("比例概率", markdown)
        self.assertIn("Shin概率", markdown)
        self.assertIn("指数概率", markdown)
        self.assertIn("正 EV 单项（主算法：比例去水）", markdown)
        self.assertIn("2 串 1 候选（主算法：比例去水）", markdown)

    def test_markdown_outputs_freshness_times_in_beijing_and_omits_row_times(self):
        report = analyze(_normalized(), max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertIn("竞彩数据抓取时间：2026-06-25 18:00:00 北京时间", markdown)
        self.assertIn("Pinnacle 数据抓取时间：2026-06-25 18:02:00 北京时间", markdown)
        self.assertIn("Pinnacle 不提供独立发布时间", markdown)
        self.assertNotIn("竞彩赔率时间", markdown)
        self.assertNotIn("Pinnacle时间", markdown)

    def test_advanced_method_failure_does_not_block_primary_report(self):
        normalized = _normalized()
        normalized["matches"] = [
            {
                "match_id": "M005",
                "home_team": "Even A",
                "away_team": "Even B",
                "start_time": "2026-06-25T12:00:00+00:00",
                "market_type": "1x2",
                "handicap": "",
                "matched_status": "matched",
                "match_confidence": 1.0,
                "sporttery": {"odds": {"home": 2.9, "draw": 2.9, "away": 2.9}},
                "market": {"odds": {"home": 3.0, "draw": 3.0, "away": 3.0}},
            }
        ]

        report = analyze(normalized, max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertEqual(report["report_status"], "ok")
        self.assertEqual(report["single_ev"][0]["method_comparison"]["shin"]["status"], "failed")
        self.assertIn("shin margin removal failed", report["data_quality_warnings"][0]["reason"])
        self.assertIn("N/A", markdown)

    def test_market_snapshot_incomplete_blocks_report(self):
        normalized = _normalized()
        normalized["snapshot_integrity"] = {
            "is_usable": False,
            "errors": ["market_snapshot_incomplete: sporttery has hhad but Pinnacle has no european_handicap"],
            "market_type_counts": {"1x2": 6},
            "sporttery_market_type_counts": {"had": 4, "hhad": 6, "ttg": 6},
        }

        report = analyze(normalized, max_data_age_minutes=1000000)
        markdown = render_markdown(report)

        self.assertEqual(report["report_status"], "blocked")
        self.assertEqual(report["single_ev"], [])
        self.assertIn("market_snapshot_incomplete", report["snapshot_integrity"]["errors"][0])
        self.assertIn("Pinnacle 玩法计数：1x2=6", markdown)


if __name__ == "__main__":
    unittest.main()
