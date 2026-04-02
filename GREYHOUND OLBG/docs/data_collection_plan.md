# Data Collection Plan

The fastest path to a real greyhound winner model is:

1. collect raw race results with prices and outcomes
2. normalize them into one runner-per-row history
3. backtest the same entry rules across time
4. tune only on the training period
5. hold out the most recent block as untouched evaluation

## Preferred source hierarchy

1. Official race-result pages with full fields for every runner in a race
2. Rich form pages with prices, split times, grades, trap, and finish positions
3. Supplemental sources for missing odds or time fields

## Minimum viable historical sample

Before trusting any ROI result, aim for:

- at least 2,000 races
- at least 10,000 runner rows
- at least 3 months of out-of-sample data
- at least 300 model-qualified bets in testing

## Raw-to-model workflow

1. Scrape or export raw source files into `data/raw/`
2. Normalize them into the required schema with `scripts/normalize_greyhound_data.py`
3. Backtest a fixed set of rules with `scripts/greyhound_backtest.py`
4. Tune thresholds with `scripts/greyhound_grid_search.py`
5. Freeze the rules before using the prompt for daily output

## Important guardrails

- Keep the raw file untouched for reproducibility.
- Never leak later races into earlier feature windows.
- Use actual available odds at decision time where possible.
- If only SP is available historically, treat the backtest as optimistic relative to live execution.
- Review ROI by track and odds band to catch overfitting.
