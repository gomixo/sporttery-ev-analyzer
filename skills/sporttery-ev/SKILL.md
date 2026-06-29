---
name: sporttery-ev
description: Analyze 2026 FIFA World Cup Sporttery odds against Pinnacle market snapshots to produce reproducible +EV reports with proportional de-vig as the primary decision method plus Shin and power/logarithmic de-vig sensitivity comparisons.
---

# Sporttery EV Analyzer

Use this skill when analyzing 2026 FIFA World Cup Sporttery odds against Pinnacle market snapshots. This project strictly supports the 2026 FIFA World Cup; do not perform general sports/event discovery.

## Safety Boundaries

- **No Auto-Betting**: Do not place bets, submit orders, or simulate payment. Output is for analysis only.
- **No WAF/Wind Control Bypass**: Never bypass captchas, login limits, or geo restrictions. If blocked, stop and request manual review.
- **No High-Frequency Scraping**: Restrict queries to low frequency. Do not run infinite scraping loops.

## Browser-Based Data Acquisition (chrome_devtools)

Because the CLI `fetch-browser` command is a manual capture placeholder, you must use your `chrome_devtools` tools to fetch data from these entry URLs:
- **Sporttery**: do NOT use the slow `match_list.php` page (it times out). Use the verified JS calculator pages directly:
  - `https://www.sporttery.cn/jc/jsq/zqspf/` for `had` (win/draw/loss) + `hhad` (handicap win/draw/loss).
  - `https://www.sporttery.cn/jc/jsq/zqzjq/` for `ttg` (total goals).
  - DOM note: each match is a `.listTr` row; parse with `innerHTML`, not `textContent` (text merges multiple span values).
- **Pinnacle**: `https://www.pinnacle.com/en/soccer/fifa-world-cup/matchups/`

### Sporttery Acquisition Steps
1. Open `new_page` and `navigate_page` to the calculator URL above (one page per market type).
2. Wait for the `.listTr` rows to render.
3. `evaluate_script` to extract each row's teams, start time, markets, and odds via `innerHTML`.
4. For `had`, set `handicap` to `""` (empty string), never `"0"`. For `hhad`, preserve the displayed handicap. Sporttery displays start times in Beijing time (`Asia/Shanghai`); convert to UTC (subtract 8h) or tag the offset (`+08:00`) before writing — never append `Z` to an unconverted local wall-clock time. Sporttery dates are always `MM-DD` format (month first); parse as `[MM, DD]` to avoid day/month swap.

### Pinnacle Acquisition Steps (JSON API, NOT DOM scraping)

Pinnacle is a React SPA with virtualized scrolling and hashed CSS class names. Scraping the DOM (clicking `+N` to expand detail pages) is the single biggest bottleneck historically (~70% of total runtime) and is fragile. Instead, call Pinnacle's own JSON endpoints from inside the page context using `evaluate_script` + same-origin `fetch()`. This stays low-frequency and sequential, does not bypass any control, and needs no separate API client.

1. Open `new_page` to the Pinnacle World Cup matchups list page so the page origin allows same-origin `fetch()` to Pinnacle API hosts.
2. Build the request headers (required by the API):
   ```
   x-api-key: CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R
   x-device-uuid: <any stable UUID>
   accept: application/json
   ```
3. Fetch league-wide matchups: `GET https://guest.api.arcadia.pinnacle.com/0.1/leagues/2686/matchups` (World Cup league id `2686`). This returns BOTH main matches and child matchups (see step 5).
4. For each **main matchup** (`participants` are full team names, no `(+N)`/digits in the name), extract `1x2` odds via `GET /matchups/{matchupId}/markets/straight` (filter `type=moneyline, period=0`). This endpoint returns a `designation` field (`home`/`draw`/`away`) on each price — use it to map prices to outcome keys. Never guess home/draw/away by price order (复盘 2026-06-29 §3.1: a positional guess produced a +117% false draw EV that was actually the away-win price).
5. **Child matchup model** (the verified way to get special markets): Pinnacle's `3-Way Handicap` and `Exact Total Goals` are NOT in `/matchups/{id}/related` (its `special` array is usually empty). They are independent child matchups returned inside `/leagues/2686/matchups`, identifiable by the trailing token in a child's participant name:
   - Contains `(+N)` / `(-N)` → `european_handicap`; preserve the displayed handicap exactly (e.g. `"-1"`, `"+1"`).
   - Contains a pure number or `N+` (e.g. `"0"`, `"1"`, `"5+"`) → `exact_total_goals`; use `handicap: ""`.
6. Fetch child-matchup prices in one call: `GET /leagues/2686/markets/straight`, then match each market's `matchupId` to its child matchup and extract odds. **This endpoint returns only `participantId`, no `designation`** — map each price to home/draw/away by joining `participantId` to the child matchup's `participants[].alignment` (home/away) plus the draw slot; never guess by price order. For `1x2` prefer the per-matchup endpoint in step 4 (which has `designation`); use league-wide only for child markets (handicap/ttg).
7. API returns **American odds** (integer prices like `4533` / `-2705`). Save them as-is in the raw snapshot and set the snapshot's top-level `odds_format: "american"` field — the normalizer converts them to decimal automatically via `american_to_decimal()` (formula: `am > 0 → 1 + am/100`; `am < 0 → 1 + 100/abs(am)`). Do NOT hand-convert in browser JS. Note: the on-page "Decimal odds" toggle only affects DOM rendering; the JSON API always returns American regardless of that setting.
8. Keep requests sequential and low-frequency. Do not open many detail pages concurrently.
9. Save the raw JSON to `data/raw/` using `write_to_file`.

#### Pinnacle Endpoint Quick Reference

| Endpoint | Use |
| --- | --- |
| `GET /matchups/{id}` | Match basics (participants, league) |
| `GET /matchups/{id}/markets/straight` | Standard markets (1x2) for one match — returns `designation` field for home/draw/away mapping |
| `GET /leagues/{id}/matchups` | **All league matches incl. child matchups** (key for special markets) |
| `GET /leagues/{id}/markets/straight` | All league standard markets (incl. child matchup prices) — only `participantId`, no `designation`; use for child markets, map via `participant.alignment` |
| `GET /matchups/{id}/related` | Related matches — `special` array usually empty; do NOT rely on it |

### Sporttery Market Capture

Capture these Sporttery market types when they are available:

- `had`: standard win/draw/loss. Use outcome keys `home`, `draw`, `away`.
- `hhad`: handicap win/draw/loss. Use outcome keys `home`, `draw`, `away`; preserve the displayed handicap in `handicap`.
- `ttg`: total goals. Use the displayed total-goals buckets as outcome keys. These keys must later align exactly with Pinnacle `exact_total_goals`.

Do not infer unavailable Sporttery markets. If a market is not on sale or not visible, leave it out and let normalization/reporting classify it as unavailable.

### Pinnacle Market Capture

Capture these Pinnacle market types (via the JSON API above):

- `1x2` or `match_winner_3way`: standard three-way match winner. Use outcome keys `home`, `draw`, `away`.
- `european_handicap`: from Pinnacle `3-Way Handicap`. Use outcome keys `home`, `draw`, `away`; preserve the displayed handicap exactly, such as `"-1"` or `"+1"`.
- `exact_total_goals`: from Pinnacle `Exact Total Goals`. Use an empty string for `handicap`; outcome keys are the total-goals buckets, such as `0`, `1`, `2`, `6+`.

Do not capture or convert these Pinnacle markets as Sporttery equivalents:

- `asian_handicap`: not equivalent to Sporttery three-way handicap win/draw/loss.
- `over_under`: not equivalent to Sporttery total-goals bucket betting.
- Any two-way market used as a substitute for a three-way or bucketed market.

If the API returns no `3-Way Handicap` / `Exact Total Goals` child matchup, do not synthesize them. Save only the markets actually returned.

Known tail-bucket mismatch: Pinnacle's last bucket may be `"6+"` while Sporttery `ttg` uses `"7+"`. The normalizer's `_partial_total_goals_market` handles this by matching the shared outcome keys and recording a `total_goals_tail_not_equivalent` warning; keep the raw keys as-is, do not rewrite them.

### Raw Snapshot Naming & Source Values
- **Sporttery**: Save to `data/raw/YYYY-MM-DD_HHMMSS1_sporttery.json` (where `HHMMSS1` is the actual fetch time) with `"source": "sporttery_browser"`.
- **Pinnacle**: Save to `data/raw/YYYY-MM-DD_HHMMSS2_pinnacle.json` (where `HHMMSS2` is the actual fetch time, typically different from `HHMMSS1` due to sequential fetching) with `"source": "pinnacle_browser"`.

## Snapshot JSON Shape

Ensure your generated raw JSON files strictly follow this structure:

```json
{
  "source": "sporttery_browser | pinnacle_browser",
  "url": "string",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ (ISO8601 UTC)",
  "odds_format": "decimal (default, may be omitted) | american (set for Pinnacle API snapshots that store raw American integer prices)",
  "raw_payload": {
    "matches": [
      {
        "source_match_id": "string",
        "home_team": "string",
        "away_team": "string",
        "start_time": "YYYY-MM-DDTHH:MM:SSZ (ISO8601 UTC)",
        "markets": [
          {
            "market_type": "had | hhad | ttg | 1x2 | ...",
            "handicap": "string (e.g. '+1', '-1.5', or empty)",
            "odds": {
              "outcome_name": 1.85
            }
          }
        ]
      }
    ]
  }
}
```
*Note: Only record displayed data. Do not use LLM reasoning to infer or fill in missing fields.*
*When `odds_format` is `"american"`, the normalizer converts every `odds` value (and each `odds_history` row) to decimal before matching/EV; omit the field or use `"decimal"` for Sporttery snapshots.*

**Timezone rule**: The `Z` suffix means true UTC only. When scraping browser-displayed local times (Sporttery shows Beijing time `Asia/Shanghai`), you MUST either (a) tag the offset explicitly (`2026-06-29T03:00:00+08:00`), or (b) convert to UTC before writing (`2026-06-28T19:00:00Z`). Never append `Z` to an unconverted local wall-clock time — it will shift every match by the timezone offset (e.g. 8h for Beijing) and cause all matches to silently fail time-delta pairing. The normalizer emits a `possible_timezone_mismatch` diagnostic when team names match but `start_time` deltas exceed the threshold.

### Market Type Mapping

The Python normalizer already recognizes these equivalent market mappings:

- Sporttery `had` -> normalized `1x2`; Pinnacle `1x2` / `match_winner_3way` -> normalized `1x2`.
- Sporttery `hhad` -> normalized `handicap_3way`; Pinnacle `european_handicap` -> normalized `handicap_3way`.
- Sporttery `ttg` -> normalized `total_goals`; Pinnacle `exact_total_goals` -> normalized `total_goals`.

Market matching requires the same teams, compatible start times, the same handicap value where applicable, and exactly matching outcome keys. If any of these fail, do not calculate EV for that market.

## Expected Data Flow

Once raw snapshots are saved, execute the calculations via the CLI. Market equivalence and odds validation are handled automatically by the Python code. Note that input file timestamps (`HHMMSS1` and `HHMMSS2`) will differ slightly due to sequential fetching.

`--sporttery-raw` and `--market-raw` accept one or more paths. When Sporttery had/hhad and ttg are captured on separate pages (`zqspf/` and `zqzjq/`), pass both files directly — the CLI merges them; no external merge script needed. Sources and `odds_format` must be consistent across merged files.

1. **Normalize snapshots**:
   ```powershell
   python -m sporttery_ev_analyzer.cli normalize `
     --sporttery-raw data/raw/2026-06-28_151631_sporttery.json data/raw/2026-06-28_151700_sporttery_ttg.json `
     --market-raw data/raw/2026-06-28_151800_pinnacle.json `
     --output data/normalized/2026-06-28_151800_matches.json
   ```

2. **Generate reports**:
   ```powershell
   python -m sporttery_ev_analyzer.cli analyze `
     --normalized data/normalized/2026-06-25_150025_matches.json `
     --json-output data/analysis/2026-06-25_150025_ev_report.json `
     --md-output data/analysis/2026-06-25_150025_ev_report.md
   ```

## Report Interpretation

- Proportional de-vig is the primary decision method.
- `positive_single_ev`, `combo_candidates`, and `conclusion` are generated from proportional de-vig only.
- Shin and power/logarithmic de-vig are sensitivity comparisons shown in JSON `method_comparison` and Markdown detail columns.
- Do not add a leg to `combo_candidates` just because Shin or power/logarithmic EV is positive.
- All de-vig calculations use each normalized match's `market.odds`, which must come from validated Pinnacle or `pinnacle_browser` source data.

## Execution Safety Checks

- The CLI will block reports (`report_status = blocked`) if data age exceeds threshold or time delta between snapshots is too large.
- 2-leg combination rules are enforced by the CLI: only different-match legs with proportional de-vig EV > 0 are combined.
- Shin or power/logarithmic de-vig failure does not necessarily block the primary report; inspect `data_quality_warnings`, and keep the primary conclusion tied to proportional de-vig.
- If validation blocks or the CLI report status is `blocked`, stop and ask for manual review. Do not attempt to bypass CLI errors using LLM calculations.
