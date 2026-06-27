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

    def test_total_goals_uses_shared_exact_outcomes_when_tail_differs(self):
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

        self.assertEqual(len(normalized["matches"]), 1)
        self.assertEqual(list(normalized["matches"][0]["sporttery"]["odds"]), ["0", "1", "2", "3", "4", "5"])
        self.assertEqual(normalized["matches"][0]["sporttery"]["odds"].keys(), normalized["matches"][0]["market"]["odds"].keys())
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


def _raw_match(home_team, away_team, market_type, handicap, odds, source="sporttery"):
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
                    "start_time": "2026-06-25T12:00:00+00:00",
                    "markets": [{"market_type": market_type, "handicap": handicap, "odds": odds}],
                }
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
