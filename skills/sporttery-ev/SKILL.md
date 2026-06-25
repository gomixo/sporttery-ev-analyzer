---
name: sporttery-ev
description: Analyze 2026 FIFA World Cup Sporttery odds against Pinnacle market snapshots to produce reproducible +EV reports.
---

# Sporttery EV Analyzer

Use this skill when analyzing 2026 FIFA World Cup Sporttery odds against Pinnacle market snapshots. This project strictly supports the 2026 FIFA World Cup; do not perform general sports/event discovery.

## Safety Boundaries

- **No Auto-Betting**: Do not place bets, submit orders, or simulate payment. Output is for analysis only.
- **No WAF/Wind Control Bypass**: Never bypass captchas, login limits, or geo restrictions. If blocked, stop and request manual review.
- **No High-Frequency Scraping**: Restrict queries to low frequency. Do not run infinite scraping loops.

## Browser-Based Data Acquisition (chrome_devtools)

Because the CLI `fetch-browser` command is a manual capture placeholder, you must use your `chrome_devtools` tools to fetch data from these entry URLs:
- **Sporttery**: `https://www.sporttery.cn/?pc=1` (If match odds are not shown directly on the main landing page, navigate to the specific football matches page, e.g. via navigation links, or go directly to `https://info.sporttery.cn/football/match_list.php`).
- **Pinnacle**: `https://www.pinnacle.com/en/soccer/fifa-world-cup/matchups/`

### Acquisition Steps
1. Open a new page using `new_page` and navigate to the entry URL using `navigate_page`.
2. Wait for the page content to load.
3. For Pinnacle, if it is not displaying decimal odds, evaluate a script or click to switch the odds display setting to **Decimal** (Pinnacle URLs/settings usually let you switch format). Do not extract American or fractional odds.
4. Execute `evaluate_script` to scrape the visible matches, start times, markets, and odds from the page DOM.
5. For Pinnacle, the fixed matchups list usually exposes only the main `1x2` market and non-equivalent Asian handicap lines. To support all three Sporttery EV markets, open each 2026 World Cup match detail page by clicking the row's right-side `+N` / `>` details entry.
6. In each Pinnacle match detail page, extract only mathematically equivalent markets:
   - `1x2` or `match_winner_3way` from the list or detail page.
   - `3-Way Handicap`, saved as `market_type: "european_handicap"`.
   - `Exact Total Goals`, saved as `market_type: "exact_total_goals"`.
7. Return to the matchups list before opening the next match detail page. Keep this low-frequency and sequential; do not open many detail pages concurrently.
8. Save the raw JSON data to `data/raw/` using `write_to_file`.

### Sporttery Market Capture

Capture these Sporttery market types when they are available:

- `had`: standard win/draw/loss. Use outcome keys `home`, `draw`, `away`.
- `hhad`: handicap win/draw/loss. Use outcome keys `home`, `draw`, `away`; preserve the displayed handicap in `handicap`.
- `ttg`: total goals. Use the displayed total-goals buckets as outcome keys. These keys must later align exactly with Pinnacle `exact_total_goals`.

Do not infer unavailable Sporttery markets. If a market is not on sale or not visible, leave it out and let normalization/reporting classify it as unavailable.

### Pinnacle Detail-Page Market Capture

Capture these Pinnacle market types:

- `1x2` or `match_winner_3way`: standard three-way match winner. Use outcome keys `home`, `draw`, `away`.
- `european_handicap`: from Pinnacle `3-Way Handicap`. Use outcome keys `home`, `draw`, `away`; preserve the displayed handicap exactly, such as `"-1"` or `"+1"`.
- `exact_total_goals`: from Pinnacle `Exact Total Goals`. Use an empty string for `handicap`; outcome keys must match Sporttery `ttg` buckets exactly, such as `0`, `1`, `2`, `3+`.

Do not capture or convert these Pinnacle markets as Sporttery equivalents:

- `asian_handicap`: not equivalent to Sporttery three-way handicap win/draw/loss.
- `over_under`: not equivalent to Sporttery total-goals bucket betting.
- Any two-way market used as a substitute for a three-way or bucketed market.

If the detail page does not contain `3-Way Handicap` or `Exact Total Goals`, do not synthesize them. Save only the markets actually displayed.

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

### Market Type Mapping

The Python normalizer already recognizes these equivalent market mappings:

- Sporttery `had` -> normalized `1x2`; Pinnacle `1x2` / `match_winner_3way` -> normalized `1x2`.
- Sporttery `hhad` -> normalized `handicap_3way`; Pinnacle `european_handicap` -> normalized `handicap_3way`.
- Sporttery `ttg` -> normalized `total_goals`; Pinnacle `exact_total_goals` -> normalized `total_goals`.

Market matching requires the same teams, compatible start times, the same handicap value where applicable, and exactly matching outcome keys. If any of these fail, do not calculate EV for that market.

## Expected Data Flow

Once raw snapshots are saved, execute the calculations via the CLI. Market equivalence and odds validation are handled automatically by the Python code. Note that input file timestamps (`HHMMSS1` and `HHMMSS2`) will differ slightly due to sequential fetching.

1. **Normalize snapshots**:
   ```powershell
   python -m sporttery_ev_analyzer.cli normalize `
     --sporttery-raw data/raw/2026-06-25_150000_sporttery.json `
     --market-raw data/raw/2026-06-25_150025_pinnacle.json `
     --output data/normalized/2026-06-25_150025_matches.json
   ```

2. **Generate reports**:
   ```powershell
   python -m sporttery_ev_analyzer.cli analyze `
     --normalized data/normalized/2026-06-25_150025_matches.json `
     --json-output data/analysis/2026-06-25_150025_ev_report.json `
     --md-output data/analysis/2026-06-25_150025_ev_report.md
   ```

## Execution Safety Checks

- The CLI will block reports (`report_status = blocked`) if data age exceeds threshold or time delta between snapshots is too large.
- 2-leg combination rules (combo candidates) are enforced by the CLI (only legs with EV > 0 are combined).
- If validation blocks or the CLI report status is `blocked`, stop and ask for manual review. Do not attempt to bypass CLI errors using LLM calculations.
