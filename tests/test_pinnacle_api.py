import unittest

from sporttery_ev_analyzer.pinnacle_api import matchups_to_raw


def _main_matchup(
    mid: int,
    home: str,
    away: str,
    start: str = "2026-06-29T19:00:00Z",
    special=None,
) -> dict:
    return {
        "id": mid,
        "startTime": start,
        "special": special,
        "league": {"id": 2686},
        "participants": [
            {"id": mid * 10 + 1, "name": home, "alignment": "home"},
            {"id": mid * 10 + 2, "name": away, "alignment": "away"},
        ],
    }


def _market(matchup_id: int, mtype: str, prices: list[dict], period: int = 0) -> dict:
    return {"matchupId": matchup_id, "type": mtype, "period": period, "prices": prices}


def _handicap_child(
    parent_id: int,
    cid: int,
    home: str,
    away: str,
    handicap: str,
) -> dict:
    return {
        "id": cid,
        "parent": {"id": parent_id},
        "special": {"description": f"3-Way Handicap {home} {handicap}"},
        "participants": [
            {"id": cid * 10 + 1, "name": f"{home} ({handicap})"},
            {"id": cid * 10 + 2, "name": f"Draw - ({home} {handicap})"},
            {"id": cid * 10 + 3, "name": f"{away} (+{handicap.lstrip('-')})"},
        ],
    }


def _ttg_child(parent_id: int, cid: int, buckets: list[str]) -> dict:
    return {
        "id": cid,
        "parent": {"id": parent_id},
        "special": {"description": "Exact Total Goals"},
        "participants": [
            {"id": cid * 100 + i, "name": bucket} for i, bucket in enumerate(buckets)
        ],
    }


class PinnacleApiMappingTests(unittest.TestCase):
    def test_main_matchup_1x2_uses_designation(self):
        main = _main_matchup(100, "Brazil", "Japan")
        markets = [_market(100, "moneyline", [
            {"designation": "home", "price": -142},
            {"designation": "draw", "price": 291},
            {"designation": "away", "price": 416},
        ])]

        raw = matchups_to_raw([main], markets, fetched_at="2026-06-29T00:00:00Z")

        self.assertEqual(len(raw["raw_payload"]["matches"]), 1)
        match = raw["raw_payload"]["matches"][0]
        self.assertEqual(match["home_team"], "Brazil")
        self.assertEqual(match["markets"][0]["odds"], {"home": -142, "draw": 291, "away": 416})

    def test_main_matchup_1x2_without_designation_is_skipped(self):
        """prices 无 designation → 该市场跳过，绝不按位置猜（复盘 §3.1 假 EV 根因）。"""
        main = _main_matchup(100, "Brazil", "Japan")
        markets = [_market(100, "moneyline", [
            {"participantId": 1, "price": -142},
            {"participantId": 2, "price": 291},
            {"participantId": 3, "price": 416},
        ])]

        raw = matchups_to_raw([main], markets, fetched_at="2026-06-29T00:00:00Z")

        # 无任何市场产出（1x2 因无 designation 被跳过），整场比赛不进输出
        self.assertEqual(raw["raw_payload"]["matches"], [])

    def test_draw_no_bet_filtered_from_main(self):
        """special 非空的 2-way 变体（Draw No Bet）被过滤，不进 main。"""
        main = _main_matchup(100, "Brazil", "Japan", special="Draw No Bet")
        markets = [_market(100, "moneyline", [
            {"designation": "home", "price": -125},
            {"designation": "away", "price": 105},
        ])]

        raw = matchups_to_raw([main], markets, fetched_at="2026-06-29T00:00:00Z")

        self.assertEqual(raw["raw_payload"]["matches"], [])

    def test_dedupe_main_matchups(self):
        """同 (home,away,startTime) 多条 → 去重取首条。"""
        main1 = _main_matchup(100, "Brazil", "Japan")
        main2 = _main_matchup(101, "Brazil", "Japan")  # 同队同时，不同 id
        markets = [_market(100, "moneyline", [
            {"designation": "home", "price": -142}, {"designation": "draw", "price": 291}, {"designation": "away", "price": 416},
        ])]

        raw = matchups_to_raw([main1, main2], markets, fetched_at="2026-06-29T00:00:00Z")

        self.assertEqual(len(raw["raw_payload"]["matches"]), 1)
        self.assertEqual(raw["raw_payload"]["matches"][0]["source_match_id"], "100")

    def test_handicap_child_uses_participant_name(self):
        """3-Way Handicap child：prices 无 designation，按 participant name 匹配主/客/Draw。"""
        main = _main_matchup(100, "Brazil", "Japan")
        markets = [
            _market(100, "moneyline", [
                {"designation": "home", "price": -142}, {"designation": "draw", "price": 291}, {"designation": "away", "price": 416},
            ]),
            _market(200, "moneyline", [
                {"participantId": 2001, "price": 209},   # Brazil (-1)
                {"participantId": 2002, "price": 267},   # Draw
                {"participantId": 2003, "price": 123},   # Japan (+1)
            ]),
        ]
        matchups = [main, _handicap_child(100, 200, "Brazil", "Japan", "-1")]

        raw = matchups_to_raw(matchups, markets, fetched_at="2026-06-29T00:00:00Z")

        match = raw["raw_payload"]["matches"][0]
        handicap_markets = [m for m in match["markets"] if m["market_type"] == "european_handicap"]
        self.assertEqual(len(handicap_markets), 1)
        self.assertEqual(handicap_markets[0]["handicap"], "-1")
        self.assertEqual(handicap_markets[0]["odds"], {"home": 209, "draw": 267, "away": 123})

    def test_total_goals_child_uses_participantid(self):
        """Exact Total Goals child：participantId → name（桶键）直接映射。"""
        buckets = ["0", "1", "2", "3", "4", "5", "6+"]
        main = _main_matchup(100, "Brazil", "Japan")
        child = _ttg_child(100, 200, buckets)
        markets = [
            _market(100, "moneyline", [
                {"designation": "home", "price": -142}, {"designation": "draw", "price": 291}, {"designation": "away", "price": 416},
            ]),
            _market(200, "moneyline", [
                {"participantId": 200 * 100 + i, "price": 100 + i * 50} for i in range(7)
            ]),
        ]

        raw = matchups_to_raw([main, child], markets, fetched_at="2026-06-29T00:00:00Z")

        match = raw["raw_payload"]["matches"][0]
        ttg_markets = [m for m in match["markets"] if m["market_type"] == "exact_total_goals"]
        self.assertEqual(len(ttg_markets), 1)
        odds = ttg_markets[0]["odds"]
        self.assertEqual(set(odds.keys()), set(buckets))
        self.assertEqual(odds["0"], 100)
        self.assertEqual(odds["6+"], 400)

    def test_output_schema(self):
        main = _main_matchup(100, "Brazil", "Japan")
        markets = [_market(100, "moneyline", [
            {"designation": "home", "price": -142}, {"designation": "draw", "price": 291}, {"designation": "away", "price": 416},
        ])]

        raw = matchups_to_raw([main], markets, fetched_at="2026-06-29T00:00:00Z")

        self.assertEqual(raw["source"], "pinnacle_browser")
        self.assertEqual(raw["odds_format"], "american")
        self.assertEqual(raw["fetched_at"], "2026-06-29T00:00:00Z")
        self.assertIn("url", raw)
        self.assertIn("matches", raw["raw_payload"])


if __name__ == "__main__":
    unittest.main()
