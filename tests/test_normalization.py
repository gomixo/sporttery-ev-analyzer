import unittest

from sporttery_ev_analyzer.normalization import normalize_pair


class NormalizationTests(unittest.TestCase):
    def test_normalize_exact_team_and_time_match(self):
        sporttery = {
            "source": "sporttery",
            "fetched_at": "2026-06-25T10:00:00+00:00",
            "raw_payload": {
                "matches": [
                    {
                        "match_id": "M001",
                        "source_match_id": "SP001",
                        "home_team": "Alpha FC",
                        "away_team": "Beta United",
                        "start_time": "2026-06-25T12:00:00+00:00",
                        "markets": [{"market_type": "1x2", "handicap": "", "odds": {"home": 2.0, "draw": 3.0, "away": 3.5}}],
                    }
                ]
            },
        }
        market = {
            "source": "pinnacle",
            "fetched_at": "2026-06-25T10:01:00+00:00",
            "raw_payload": {
                "matches": [
                    {
                        "source_match_id": "PN001",
                        "home_team": "Alpha FC",
                        "away_team": "Beta United",
                        "start_time": "2026-06-25T12:05:00+00:00",
                        "markets": [{"market_type": "1x2", "handicap": "", "odds": {"home": 1.9, "draw": 3.2, "away": 4.0}}],
                    }
                ]
            },
        }

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["matches"][0]["match_id"], "M001")
        self.assertEqual(normalized["unmatched"], [])

    def test_time_delta_mismatch_emits_timezone_diagnostic(self):
        """球队名匹配但 start_time 偏差超阈值时（如北京时间误标 Z），应报 possible_timezone_mismatch。

        复盘 2026-06-28 §4：Sporttery 显示北京时间 03:00 被直接加 Z 当 UTC，与 Pinnacle 真 UTC
        19:00 相差 8 小时，导致全部 unmatched 但无诊断。
        """
        sporttery = _raw_match_at("日本", "瑞典", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5}, "2026-06-25T03:00:00Z")
        market = _raw_match_at("Japan", "Sweden", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, "2026-06-24T19:00:00Z", source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=30)

        self.assertEqual(normalized["matches"], [])
        self.assertFalse(normalized["source_validation"]["is_usable"])
        self.assertTrue(any("possible_timezone_mismatch" in err for err in normalized["source_validation"]["errors"]))

    def test_normal_match_does_not_emit_timezone_diagnostic(self):
        """球队名与时间都正常匹配时，不应触发时区诊断（回归保障）。"""
        sporttery = _raw_match("韩国", "日本", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})
        market = _raw_match("Korea Republic", "Japan", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["source_validation"]["errors"], [])

    def test_world_cup_team_alias_matches_country_names(self):
        sporttery = _raw_match("韩国", "日本", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})
        market = _raw_match("Korea Republic", "Japan", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["matches"][0]["market_type"], "1x2")
        self.assertEqual(normalized["matches"][0]["source_market_types"], {"sporttery": "had", "market": "1x2"})

    def test_club_aliases_are_not_matched_by_world_cup_aliases(self):
        sporttery = _raw_match("曼彻斯特联", "日本", "1x2", "", {"home": 2.0, "draw": 3.0, "away": 3.5})
        market = _raw_match("曼联", "Japan", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"], [])
        self.assertEqual(len(normalized["unmatched"]), 2)

    def test_three_way_handicap_does_not_match_two_way_handicap(self):
        sporttery = _raw_match("韩国", "日本", "hhad", "-1", {"home": 3.0, "draw": 3.4, "away": 2.0})
        market = _raw_match("Korea Republic", "Japan", "asian_handicap", "-1", {"home": 1.9, "away": 1.9}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"], [])
        self.assertTrue(any(item["reason"] == "asian_handicap_is_not_equivalent_to_sporttery_3way_handicap" for item in normalized["unmatched"]))

    def test_three_way_handicap_matches_equivalent_three_way_market(self):
        sporttery = _raw_match("韩国", "日本", "hhad", "-1", {"home": 3.0, "draw": 3.4, "away": 2.0})
        market = _raw_match("Korea Republic", "Japan", "european_handicap", "-1", {"home": 2.8, "draw": 3.3, "away": 2.1}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["matches"][0]["market_type"], "handicap_3way")

    def test_exact_total_goals_matches_equivalent_pinnacle_bucket_market(self):
        sporttery = _raw_match("韩国", "日本", "ttg", "", {"0": 8.0, "1": 4.0, "2": 3.2, "3+": 2.1}, source="sporttery")
        market = _raw_match("Korea Republic", "Japan", "exact_total_goals", "", {"0": 7.5, "1": 4.2, "2": 3.0, "3+": 2.2}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["matches"][0]["market_type"], "total_goals")

    def test_odds_history_uses_latest_published_row(self):
        sporttery = _raw_match("日本", "瑞典", "had", "", {"home": 1.64, "draw": 3.52, "away": 4.25}, source="sporttery")
        sporttery["raw_payload"]["matches"][0]["markets"][0]["odds_history"] = [
            {
                "published_at": "2026-06-25T04:20:25+00:00",
                "odds": {"home": 1.64, "draw": 3.52, "away": 4.25},
            },
            {
                "published_at": "2026-06-25T05:33:38+00:00",
                "odds": {"home": 1.60, "draw": 3.57, "away": 4.45},
            },
        ]
        market = _raw_match("Japan", "Sweden", "1x2", "", {"home": 1.88, "draw": 3.85, "away": 4.75}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"][0]["sporttery"]["odds"], {"home": 1.60, "draw": 3.57, "away": 4.45})
        self.assertEqual(normalized["matches"][0]["sporttery"]["updated_at"], "2026-06-25T05:33:38+00:00")

    def test_market_odds_format_american_is_converted_before_merge(self):
        """标 odds_format=american 的 Pinnacle 快照存美式整数赔率，normalize 应先转小数再匹配。

        美式 +150/-200 -> 2.5/1.5，需与竞彩小数赔率正常匹配并进入 EV 计算。
        """
        sporttery = _raw_match("日本", "瑞典", "had", "", {"home": 2.50, "draw": 3.50, "away": 3.00}, source="sporttery")
        market = _raw_match("Japan", "Sweden", "1x2", "", {"home": 150, "draw": 300, "away": -200}, source="pinnacle")
        market["odds_format"] = "american"

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        # market 侧应已被转成小数：150->2.5, 300->4.0, -200->1.5
        self.assertEqual(normalized["matches"][0]["market"]["odds"], {"home": 2.5, "draw": 4.0, "away": 1.5})
        self.assertEqual(normalized["unmatched"], [])

    def test_market_odds_format_american_conversion_does_not_mutate_raw(self):
        sporttery = _raw_match("日本", "瑞典", "had", "", {"home": 2.50, "draw": 3.50, "away": 3.00}, source="sporttery")
        market = _raw_match("Japan", "Sweden", "1x2", "", {"home": 150, "draw": 300, "away": -200}, source="pinnacle")
        market["odds_format"] = "american"

        first = normalize_pair(sporttery, market, max_start_delta_minutes=10)
        second = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(first["matches"][0]["market"]["odds"], {"home": 2.5, "draw": 4.0, "away": 1.5})
        self.assertEqual(second["matches"][0]["market"]["odds"], {"home": 2.5, "draw": 4.0, "away": 1.5})
        self.assertEqual(market["raw_payload"]["matches"][0]["markets"][0]["odds"], {"home": 150, "draw": 300, "away": -200})

    def test_market_odds_format_american_converts_odds_history_too(self):
        """odds_format=american 时 odds_history 的历史行也应一并转小数，latest 选取基于转换后值。"""
        sporttery = _raw_match("日本", "瑞典", "had", "", {"home": 2.50, "draw": 4.00, "away": 1.50}, source="sporttery")
        market = _raw_match("Japan", "Sweden", "1x2", "", {}, source="pinnacle")
        market["odds_format"] = "american"
        market["raw_payload"]["matches"][0]["markets"][0]["odds_history"] = [
            {"published_at": "2026-06-25T04:20:25+00:00", "odds": {"home": 150, "draw": 300, "away": -200}},
            {"published_at": "2026-06-25T05:33:38+00:00", "odds": {"home": 130, "draw": 350, "away": -180}},
        ]

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        # latest 是 05:33 行，美式 130->2.3, 350->4.5, -180->1.5556
        self.assertEqual(normalized["matches"][0]["market"]["odds"]["home"], 2.3)
        self.assertEqual(normalized["matches"][0]["market"]["odds"]["draw"], 4.5)
        self.assertAlmostEqual(normalized["matches"][0]["market"]["odds"]["away"], 1 + 100 / 180, places=6)
        self.assertEqual(normalized["matches"][0]["market"]["updated_at"], "2026-06-25T05:33:38+00:00")

    def test_missing_odds_format_leaves_odds_untouched(self):
        """无 odds_format 字段（历史快照）不做任何转换，向后兼容。"""
        sporttery = _raw_match("日本", "瑞典", "had", "", {"home": 2.50, "draw": 3.50, "away": 3.00}, source="sporttery")
        market = _raw_match("Japan", "Sweden", "1x2", "", {"home": 2.5, "draw": 4.0, "away": 1.5}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"][0]["market"]["odds"], {"home": 2.5, "draw": 4.0, "away": 1.5})

    def test_total_goals_does_not_match_over_under(self):
        sporttery = _raw_match("韩国", "日本", "ttg", "", {"0": 8.0, "1": 4.0, "2": 3.2, "3+": 2.1}, source="sporttery")
        market = _raw_match("Korea Republic", "Japan", "over_under", "2.5", {"over": 1.9, "under": 1.9}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"], [])
        self.assertTrue(any(item["reason"] == "over_under_is_not_equivalent_to_sporttery_total_goals" for item in normalized["unmatched"]))

    def test_outcome_mismatch_is_not_merged(self):
        sporttery = _raw_match("韩国", "日本", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})
        market = _raw_match("Korea Republic", "Japan", "1x2", "", {"home": 1.9, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"], [])
        self.assertTrue(any(item["reason"] == "no_equivalent_market" for item in normalized["unmatched"]))

    def test_had_handicap_zero_matches_pinnacle_1x2_empty_handicap(self):
        """非让球玩法 "0" 与 "" 等价：Sporttery had 的 handicap "0" 应与 Pinnacle 1x2 的 "" 匹配。

        复盘 2026-06-28 §4.1：原始 raw 中 had handicap 为 "0" 而 1x2 为 ""，导致 6 场 1x2 全部
        unmatched。标准化层应把非让球玩法的 "0" 归一化为 ""。
        """
        sporttery = _raw_match("韩国", "日本", "had", "0", {"home": 2.0, "draw": 3.0, "away": 3.5})
        market = _raw_match("Korea Republic", "Japan", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(normalized["matches"][0]["market_type"], "1x2")
        self.assertEqual(normalized["unmatched"], [])

    def test_total_goals_tail_mismatch_is_not_calculable(self):
        sporttery = _raw_match(
            "Alpha FC",
            "Beta United",
            "ttg",
            "",
            {"0": 8.0, "1": 4.0, "2": 3.2, "3": 3.8, "4": 6.0, "5": 12.0, "6": 20.0, "7+": 30.0},
            source="sporttery",
        )
        market = _raw_match(
            "Alpha FC",
            "Beta United",
            "exact_total_goals",
            "",
            {"0": 7.5, "1": 4.2, "2": 3.0, "3": 4.0, "4": 6.5, "5": 11.0, "6+": 18.0},
            source="pinnacle",
        )

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertEqual(normalized["matches"], [])
        self.assertTrue(normalized["snapshot_integrity"]["is_usable"])
        self.assertTrue(any(item["reason"] == "total_goals_tail_not_equivalent" for item in normalized["unmatched"]))

    def test_snapshot_integrity_flags_missing_pinnacle_handicap_and_total_goals(self):
        sporttery = {
            "source": "sporttery",
            "fetched_at": "2026-06-25T10:00:00+00:00",
            "raw_payload": {
                "matches": [
                    {
                        "source_match_id": "SP001",
                        "home_team": "Alpha FC",
                        "away_team": "Beta United",
                        "start_time": "2026-06-25T12:00:00+00:00",
                        "markets": [
                            {"market_type": "had", "handicap": "", "odds": {"home": 2.0, "draw": 3.0, "away": 3.5}},
                            {"market_type": "hhad", "handicap": "-1", "odds": {"home": 3.0, "draw": 3.4, "away": 2.0}},
                            {"market_type": "ttg", "handicap": "", "odds": {"0": 8.0, "1": 4.0, "2": 3.2, "3+": 2.1}},
                        ],
                    }
                ]
            },
        }
        market = _raw_match("Alpha FC", "Beta United", "1x2", "", {"home": 1.9, "draw": 3.2, "away": 4.0}, source="pinnacle")

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertFalse(normalized["snapshot_integrity"]["is_usable"])
        self.assertEqual(normalized["snapshot_integrity"]["market_type_counts"], {"1x2": 1})
        self.assertTrue(any("market_snapshot_incomplete" in error for error in normalized["snapshot_integrity"]["errors"]))

    def test_snapshot_integrity_does_not_block_per_match_missing_equivalent_market(self):
        sporttery = {
            "source": "sporttery",
            "fetched_at": "2026-06-25T10:00:00+00:00",
            "raw_payload": {
                "matches": [
                    {
                        "source_match_id": "SP001",
                        "home_team": "Alpha FC",
                        "away_team": "Beta United",
                        "start_time": "2026-06-25T12:00:00+00:00",
                        "markets": [{"market_type": "ttg", "handicap": "", "odds": {"0": 8.0, "1": 4.0, "2+": 2.1}}],
                    },
                    {
                        "source_match_id": "SP002",
                        "home_team": "Gamma City",
                        "away_team": "Delta Town",
                        "start_time": "2026-06-25T13:00:00+00:00",
                        "markets": [{"market_type": "ttg", "handicap": "", "odds": {"0": 8.0, "1": 4.0, "2+": 2.1}}],
                    },
                ]
            },
        }
        market = {
            "source": "pinnacle",
            "fetched_at": "2026-06-25T10:00:00+00:00",
            "raw_payload": {
                "matches": [
                    {
                        "source_match_id": "PN001",
                        "home_team": "Alpha FC",
                        "away_team": "Beta United",
                        "start_time": "2026-06-25T12:00:00+00:00",
                        "markets": [{"market_type": "exact_total_goals", "handicap": "", "odds": {"0": 7.5, "1": 4.2, "2+": 2.2}}],
                    },
                    {
                        "source_match_id": "PN002",
                        "home_team": "Gamma City",
                        "away_team": "Delta Town",
                        "start_time": "2026-06-25T13:00:00+00:00",
                        "markets": [{"market_type": "1x2", "handicap": "", "odds": {"home": 1.9, "draw": 3.2, "away": 4.0}}],
                    },
                ]
            },
        }

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        self.assertTrue(normalized["snapshot_integrity"]["is_usable"])
        self.assertTrue(any(item["reason"] == "no_equivalent_market" for item in normalized["unmatched"]))


def _raw_match(home_team, away_team, market_type, handicap, odds, source="sporttery"):
    return _raw_match_at(home_team, away_team, market_type, handicap, odds, "2026-06-25T12:00:00+00:00", source)


def _raw_match_at(home_team, away_team, market_type, handicap, odds, start_time, source="sporttery"):
    return {
        "source": source,
        "fetched_at": "2026-06-25T10:00:00+00:00",
        "raw_payload": {
            "matches": [
                {
                    "match_id": "M001",
                    "source_match_id": "SRC001",
                    "home_team": home_team,
                    "away_team": away_team,
                    "start_time": start_time,
                    "markets": [{"market_type": market_type, "handicap": handicap, "odds": odds}],
                }
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
