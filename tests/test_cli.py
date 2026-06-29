import unittest

from sporttery_ev_analyzer.cli import merge_raw_files


def _raw(source: str, matches, *, fetched_at: str = "2026-06-25T10:00:00+00:00", odds_format=None):
    raw = {
        "source": source,
        "url": "https://example.com",
        "fetched_at": fetched_at,
        "raw_payload": {"matches": matches},
    }
    if odds_format is not None:
        raw["odds_format"] = odds_format
    return raw


def _match(home, away, market_type, handicap, odds, source_match_id="SRC001"):
    return {
        "source_match_id": source_match_id,
        "home_team": home,
        "away_team": away,
        "start_time": "2026-06-25T12:00:00+00:00",
        "markets": [{"market_type": market_type, "handicap": handicap, "odds": odds}],
    }

class MergeRawFilesTests(unittest.TestCase):
    def test_single_raw_returned_unchanged(self):
        matches = [_match("A", "B", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})]
        raw = _raw("sporttery", matches)

        merged = merge_raw_files([raw])

        self.assertIs(merged, raw)

    def test_multiple_raws_merge_same_match_markets(self):
        # had/hhad 在一份，ttg 在另一份，同一场比赛（同 source_match_id）应合并进同一行
        raw1 = _raw(
            "sporttery",
            [_match("日本", "瑞典", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})],
        )
        raw2 = _raw(
            "sporttery",
            [_match("日本", "瑞典", "ttg", "", {"0": 8.0, "1": 4.0, "2": 3.2, "3+": 2.1})],
            fetched_at="2026-06-25T10:02:00+00:00",
        )

        merged = merge_raw_files([raw1, raw2])

        # 同一场比赛合并成一行，而非产生两个重复行（修复 used_market_indexes 锁死 bug）
        self.assertEqual(len(merged["raw_payload"]["matches"]), 1)
        market_types = [m["market_type"] for m in merged["raw_payload"]["matches"][0]["markets"]]
        self.assertEqual(sorted(market_types), ["had", "ttg"])

    def test_merged_same_match_markets_survive_normalize(self):
        """端到端：合并后的 sporttery raw 跑 normalize_pair，had 和 ttg 都应 matched。

        复盘 2026-06-29 §3.3 / Gemini 报告 §3.1：merge_raw_files 旧实现按行 extend
        产生重复行，触发 used_market_indexes 锁死导致 ttg no_market_match。
        """
        from sporttery_ev_analyzer.normalization import normalize_pair

        raw1 = _raw(
            "sporttery",
            [_match("韩国", "日本", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5})],
        )
        raw2 = _raw(
            "sporttery",
            [_match("韩国", "日本", "ttg", "", {"0": 8.0, "1": 4.0, "2": 3.2, "3+": 2.1})],
            fetched_at="2026-06-25T10:02:00+00:00",
        )
        sporttery = merge_raw_files([raw1, raw2])
        market = _raw(
            "pinnacle",
            [
                {
                    "source_match_id": "PN001",
                    "home_team": "Korea Republic",
                    "away_team": "Japan",
                    "start_time": "2026-06-25T12:00:00+00:00",
                    "markets": [
                        {"market_type": "1x2", "handicap": "", "odds": {"home": 1.9, "draw": 3.2, "away": 4.0}},
                        {"market_type": "exact_total_goals", "handicap": "", "odds": {"0": 7.5, "1": 4.2, "2": 3.0, "3+": 2.2}},
                    ],
                }
            ],
        )

        normalized = normalize_pair(sporttery, market, max_start_delta_minutes=10)

        market_types = {m["market_type"] for m in normalized["matches"]}
        self.assertIn("1x2", market_types)
        self.assertIn("total_goals", market_types)
        # 不应有 no_market_match（锁死 bug 的症状）
        self.assertFalse(any(
            item.get("reason") == "no_market_match" and item.get("source") == "sporttery"
            for item in normalized["unmatched"]
        ))

    def test_different_matches_not_merged(self):
        """两份 raw 含不同比赛，合并后仍是两行（回归保障）。"""
        raw1 = _raw(
            "sporttery",
            [_match("日本", "瑞典", "had", "", {"home": 2.0, "draw": 3.0, "away": 3.5}, source_match_id="M001")],
        )
        raw2 = _raw(
            "sporttery",
            [_match("巴西", "德国", "had", "", {"home": 1.5, "draw": 3.5, "away": 5.0}, source_match_id="M002")],
        )

        merged = merge_raw_files([raw1, raw2])

        self.assertEqual(len(merged["raw_payload"]["matches"]), 2)

    def test_fetched_at_takes_earliest(self):
        raw1 = _raw("sporttery", [], fetched_at="2026-06-25T10:05:00+00:00")
        raw2 = _raw("sporttery", [], fetched_at="2026-06-25T10:01:00+00:00")

        merged = merge_raw_files([raw1, raw2])

        self.assertEqual(merged["fetched_at"], "2026-06-25T10:01:00+00:00")

    def test_mixed_sources_rejected(self):
        raw1 = _raw("sporttery", [])
        raw2 = _raw("pinnacle", [])

        with self.assertRaises(ValueError) as ctx:
            merge_raw_files([raw1, raw2])
        self.assertIn("different sources", str(ctx.exception))

    def test_mixed_odds_format_rejected(self):
        raw1 = _raw("pinnacle", [], odds_format="american")
        raw2 = _raw("pinnacle", [], odds_format="decimal")

        with self.assertRaises(ValueError) as ctx:
            merge_raw_files([raw1, raw2])
        self.assertIn("different odds_format", str(ctx.exception))

    def test_consistent_odds_format_preserved(self):
        raw1 = _raw("pinnacle", [_match("A", "B", "1x2", "", {"home": 150, "draw": 300, "away": -200}, source_match_id="PN001")], odds_format="american")
        raw2 = _raw("pinnacle", [_match("C", "D", "1x2", "", {"home": 100, "draw": 300, "away": -150}, source_match_id="PN002")], odds_format="american")

        merged = merge_raw_files([raw1, raw2])

        self.assertEqual(merged["odds_format"], "american")
        self.assertEqual(len(merged["raw_payload"]["matches"]), 2)


if __name__ == "__main__":
    unittest.main()
