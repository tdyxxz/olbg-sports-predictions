# Greyhound Profit Strategy

This project is optimized for profit, not hit rate.

## Core principles

1. Treat the market as the baseline. A selection is only actionable when our model probability is meaningfully higher than the market-implied probability from the starting price or closing price.
2. Bet one dog per race at most. Greyhound win markets are tight, and spreading across multiple runners in the same race usually destroys edge.
3. Use chronological validation only. Never let later races influence features for earlier races.
4. Skip aggressively. The model should pass most races unless the edge, price range, and race-shape filters all align.
5. Optimize on ROI and drawdown, not only log loss or accuracy.

## Rugby-style rules worth keeping

These transfer well from profitable rugby workflows:

- Use market odds as an anchor feature, not something to ignore.
- Demand a clear edge threshold before betting.
- Backtest with fixed rules and no race-by-race overrides.
- Prefer stable price bands over extremes.
- Review performance by segment instead of relying on one global ROI number.

## Winner-only betting rules

The default strategy in `scripts/greyhound_backtest.py` is:

- Score every runner with a trained probability model.
- Normalize probabilities inside each race so the total is 100%.
- Pick only the top-rated runner in each race.
- Bet only if all of the following are true:
  - model edge is at least the configured threshold
  - odds are within the configured min/max band
  - probability gap over the second choice is large enough

## Default profitability assumptions

These are the first settings to test, not permanent truths:

- Odds band: `2.0` to `6.5` decimal
- Minimum edge over market: `0.05`
- Minimum gap over second choice: `0.04`
- Flat stake: `1.0` unit

## Metrics that matter

Track these in every run:

- ROI
- strike rate
- total bets
- profit
- longest losing run
- ROI by odds band
- ROI by track
- ROI by model edge bucket

## What we need in the data

Per runner, we need enough history to estimate:

- recent win and place rates
- track suitability
- trap suitability
- distance suitability
- grade movement
- freshness
- market position
- optional early pace and speed signals

## Suggested iteration order

1. Build a clean historical runner file.
2. Run the baseline script with only market + rolling form features.
3. Inspect ROI by edge bucket and price band.
4. Add split times and race times if available.
5. Add track-bias and trap-bias features only if they improve walk-forward ROI.
6. Freeze the best rules and use the output prompt only for presentation.
