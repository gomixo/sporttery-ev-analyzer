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
4. Execute `evaluate_script` to scrape the matches, start times, markets, and odds from the page DOM.
5. Save the raw JSON data to `data/raw/` using `write_to_file`.

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
