# Golf Top-10 Profitability Framework

This workspace is now centered on a single betting problem:

- Predict whether a golfer will finish top 10.
- Bet only when the estimated probability is materially above the bookmaker's implied probability.
- Measure success by ROI, not by narrative quality or raw pick accuracy.

## What changed from the original prompt

The starting text in `GOLF.txt` is broad and market-heavy. For profitability, that is a trap. The revised approach borrows the parts that transfer well from profitable single-market rugby workflows:

- Specialize in one market.
- Use a repeatable pre-bet feature set.
- Require a minimum edge over implied probability.
- Cap the number of bets per event.
- Avoid forcing action on weak cards.
- Track closing line value when available.
- Evaluate with walk-forward backtests, not hindsight writeups.

## Files

- `prompts/golf_top10_profit_prompt.txt`: revised prompt focused only on profitable top-10 selections.
- `prompts/golf_top10_prediction_prompt_v2.txt`: production prompt for upcoming-event Top 10 Finish predictions in ChatGPT.
- `scripts/backtest_top10.py`: CSV-driven backtest and selection engine.
- `scripts/fetch_datagolf_top10_history.py`: pulls DataGolf historical `top_10` odds and merges them with archived DataGolf pre-tournament top-10 probabilities.
- `scripts/fetch_espn_golf_results.py`: pulls completed tournament leaderboards and top-10 outcomes for the last N golf events from ESPN schedule and leaderboard pages.
- `scripts/build_lvsb_top10_history.py`: scrapes Las Vegas Sports Betting's public PGA archive pages for historical `Top 10 Finish` prices and joins them to the ESPN results file.
- `scripts/backtest_top10_proxy_market.py`: fallback walk-forward backtest that uses a synthetic market proxy built from prior results when real historical top-10 prices are unavailable.
- `data/templates/golf_top10_training_template.csv`: starter schema for historical event/player rows.
- `docs/top10_strategy.md`: practical strategy notes and data requirements.
- `docs/prompt_usage.md`: how to use the production prediction prompt in ChatGPT.

## Recommended data sources

Best paid source:

- DataGolf historical odds API for `top_10` markets plus historical raw/event stats.

The DataGolf docs explicitly list:

- `historical-odds/outrights` with `market=top_10` and opening/closing lines plus outcomes.
- `preds/pre-tournament-archive` for archived pre-tournament finish-position probabilities.

That combination is the cleanest profitability backtest input because it lets us compare sportsbook price against an archived model probability that existed before the tournament started.

Good fallbacks:

- Official PGA Tour / DP World Tour results data for finish positions.
- Historical odds providers such as The Odds API or SportsDataIO if you already have access.
- Your own archived sportsbook exports if you have them.

## Core idea

For each player-event row:

1. Load pre-tournament features.
2. Estimate top-10 probability from a weighted score.
3. Convert available odds into implied probability.
4. Bet only when:
   - `model_prob - implied_prob >= min_edge`
   - odds fall inside a profitable band
   - the player clears the model score floor
   - the event has not already hit its max number of bets
5. Grade the bet from the actual top-10 result.

## CSV expectations

The backtester expects one row per player per event with these important fields:

- `event_id`
- `event_date`
- `player_name`
- `top10_odds_open`
- `top10_odds_close`
- `finish_position`
- `top10_result`
- feature columns listed in the template

The script is robust to either `finish_position` or `top10_result` being present. If `top10_result` is blank, it derives it from `finish_position`.

## Example usage

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\backtest_top10.py' `
  --input '.\data\templates\golf_top10_training_template.csv' `
  --output '.\outputs\top10_backtest_report.json' `
  --bets-output '.\outputs\top10_bets.csv'
```

## DataGolf pipeline

If you have a DataGolf key, the quickest path is:

```powershell
$env:DATAGOLF_API_KEY='YOUR_KEY_HERE'
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\fetch_datagolf_top10_history.py' `
  --tours 'pga,euro' `
  --years '2023,2024,2025' `
  --books 'draftkings,fanduel,pinnacle'
```

That writes merged files into `data/raw/datagolf/` with:

- sportsbook opening and closing `top_10` odds
- bet outcome or finish result when available
- archived DataGolf top-10 probability when matched

Then backtest directly from the merged file:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\backtest_top10.py' `
  --input '.\data\raw\datagolf\pga_all_merged_top10.csv' `
  --output '.\outputs\top10_backtest_report.json' `
  --bets-output '.\outputs\top10_bets.csv' `
  --min-edge 0.03 `
  --max-bets-per-event 1
```

If the merged file includes `dg_top10_prob`, the backtester will use that direct archived model probability instead of the local weighted-score estimate.

## Results pipeline

The last-100-tournaments results side can be collected automatically with ESPN leaderboard pages:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\fetch_espn_golf_results.py' `
  --tours 'pga' `
  --seasons '2026,2025,2024' `
  --limit 100 `
  --output '.\data\raw\espn\golf_last_100_tournaments_results.csv'
```

This produces one row per player per event and includes:

- tournament id
- event name
- event dates
- finishing position
- player name
- top-10 result flag

## Public archive pipeline

Without a paid odds feed, the best public archive found so far is Las Vegas Sports Betting's historical PGA pages, which include line-by-line `Top 10 Finish` prices sourced from a sportsbook and dated archive pages.

Build the merged historical prices plus outcomes dataset with:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\build_lvsb_top10_history.py' `
  --results '.\data\raw\espn\golf_last_100_tournaments_results.csv' `
  --output '.\data\raw\lvsb\golf_top10_history_lvsb.csv' `
  --unmatched-output '.\data\raw\lvsb\golf_top10_history_lvsb_unmatched.csv'
```

The merged file contains:

- event
- player
- finishing position
- top-10 outcome
- historical top-10 closing price in decimal and American format
- archive URL
- source book when listed on the archive page

## Proxy fallback

If public historical top-10 odds coverage is too thin, run the walk-forward proxy backtest:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\backtest_top10_proxy_market.py' `
  --input '.\data\raw\espn\golf_2023_2026_results.csv' `
  --output '.\outputs\top10_proxy_market_report.json' `
  --bets-output '.\outputs\top10_proxy_market_bets.csv'
```

This is not a sportsbook-grade ROI test. It is a fallback that asks whether a richer rolling-form model can beat a simpler market-style baseline using only parsed historical results.

To search for more profitable thresholds on your historical data:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\backtest_top10.py' `
  --input '.\data\historical\golf_top10_history.csv' `
  --output '.\outputs\top10_backtest_report.json' `
  --bets-output '.\outputs\top10_bets.csv' `
  --optimize
```

To manually test tighter or looser profitability rules without editing code:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' `
  '.\scripts\backtest_top10.py' `
  --input '.\data\historical\golf_top10_history.csv' `
  --output '.\outputs\top10_backtest_report.json' `
  --bets-output '.\outputs\top10_bets.csv' `
  --min-edge 0.03 `
  --max-odds 6.0 `
  --max-bets-per-event 1
```

## Practical next step

Fill the template with real historical rows first. Once we have enough seasons of data, we can tighten the scoring weights, probability calibration, odds bands, and event-level caps using actual ROI instead of assumptions.
