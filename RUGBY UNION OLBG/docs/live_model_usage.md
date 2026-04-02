# Live Model Usage

## Current Live Rules

The active rugby model currently supports two live markets:

- Bet `UNDER`
- Bet `AWAY WINNER` in Super Rugby only

### Totals rule

- Bet `UNDER`
- only when model edge is at least `0.07`
- only when total line is between `46.5` and `66.5`
- only when the line is no more than `2.0` points above the competition's recent average total line

### Outright winner rule

- Bet `AWAY WINNER`
- only in `Super Rugby`
- only when away model edge is at least `0.05`
- only when away odds are between `1.50` and `2.20`

## What this means in practice

This is not a general rugby prediction model.

It is a narrow market-selection model that tries to find:

- totals that are slightly too high for the competition,
- teams whose recent scoring path supports lower output,
- and under prices where the estimated probability is clearly above the sportsbook's implied number.
- plus a narrow Super Rugby away-winner pocket where the model has shown a small but repeatable edge

## When to skip

Skip the match if:

- the line is too low,
- the line is too high,
- the estimated edge is below `0.07`,
- or the recent scoring data is too noisy or incomplete.

For outright winners, skip if:

- the match is not Super Rugby,
- the candidate side is not the away team,
- the away odds are outside `1.50` to `2.20`,
- or the away edge is below `0.05`.

## Current limitations

- sample size is still modest
- historical scraping coverage is uneven by league and season
- the model currently relies on sportsbook odds and recent results only
- weather, referee, and lineup disruption are not yet in the live rule
- handicap is not live yet because we do not have enough reliable historical handicap pricing in the backtest set

## Safe operating assumption

Treat the model as an early profitable prototype, not a finished system.

Use it exactly as written and avoid adding extra subjective picks around it unless we backtest those changes first.
