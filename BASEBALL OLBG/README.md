# Baseball OLBG

This folder now has a first-pass MLB prediction runner built for repeatable daily use.

## Current Source Stack

- `statsapi.mlb.com`
  - schedule and game status
  - probable pitchers
  - standings and run differential
  - team recent game logs
  - pitcher season stats
- `vegasinsider.com/mlb/odds/las-vegas/`
  - public consensus moneyline odds parsed from the daily MLB board

## What The Script Does

`scripts/predict_mlb_card.py` builds a no-key moneyline card for pre-game MLB matchups.

It currently blends:

- current-season win percentage
- previous-season win percentage
- current-season run differential per game
- previous-season run differential per game
- recent five-game form
- probable pitcher blended stats using current and previous season ERA, WHIP, and K/9
- implied probability from the current consensus moneyline

It then keeps only selections where the estimated edge exceeds the configured threshold.

## Historical Backtest

Historical odds are stored in:

- `data/historical/mlb_odds_dataset.json`

This dataset came from the public release in:

- [ArnavSaraogi/mlb-odds-scraper](https://github.com/ArnavSaraogi/mlb-odds-scraper)

It covers MLB odds and final results from 2021-04-01 through 2025-08-16.

Run the first backtest with:

```powershell
python .\scripts\backtest_moneyline_model.py
```

Optional stricter filter:

```powershell
python .\scripts\backtest_moneyline_model.py --min-edge 0.05 --min-games 10
```

Backtest outputs:

- `outputs/moneyline_backtest_summary.json`
- `outputs/moneyline_backtest_bets.json`
- `outputs/moneyline_backtest_report.md`

## Daily Odds Snapshot

Archive the current VegasInsider MLB board with:

```powershell
python .\scripts\archive_daily_odds.py --date 2026-04-01
```

This writes:

- `data/snapshots/mlb_moneylines_YYYYMMDD.json`
- `data/snapshots/mlb_moneylines_YYYYMMDD.csv`

## Run It

From this folder:

```powershell
python .\scripts\predict_mlb_card.py --date 2026-04-01
```

Optional threshold override:

```powershell
python .\scripts\predict_mlb_card.py --date 2026-04-01 --min-edge 0.03
```

## Outputs

The script writes:

- `outputs/mlb_predictions_YYYYMMDD.json`
- `outputs/mlb_predictions_YYYYMMDD.md`

## Important Limits

- This is a first-pass heuristic model, not a backtested MLB model yet.
- The current implementation is strongest for the current live daily board because the VegasInsider page is a daily odds page.
- It currently outputs moneyline picks only.
- Run line and totals need a second pass because they require a more reliable line-level source and better bullpen and total-environment features.

## Next Steps

1. Store historical daily odds snapshots.
2. Add a backtest runner using the same feature set.
3. Expand to run line and totals after the moneyline workflow is stable.
4. Standardize the same card-generation/reporting pattern across the other sports folders.
