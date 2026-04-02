# Historical Data Collection Plan

## Goal

Populate `data/historical_matches_sample.csv` with real rugby union matches and true pre-match betting prices so the backtest means something.

## Best dataset shape

One row per match, with closing prices and only features known before kickoff.

## Minimum viable fields

- match date
- competition
- teams
- closing moneyline odds
- closing handicap line and odds
- closing total line and odds
- final score

## High-value feature fields

- recent win rate
- recent average margin
- set-piece rating
- goal-kicking rating
- weather severity
- referee penalty bias
- rest days
- travel fatigue
- international absence severity
- competition pace factor
- ATS cover rate

## Recommended source stack

Use separate sources for prices and results rather than hoping one source is perfect at both.

### Prices

Look for a provider with:

- historical pre-match odds,
- handicap and totals coverage,
- bookmaker identifiers,
- and timestamped snapshots if possible.

### Results

Use official competition archives or reliable match result feeds to confirm final scores and match dates.

## Collection workflow

1. Pull or export historical odds by competition and season.
2. Pull final results for the same competitions and date ranges.
3. Standardise team names.
4. Keep only closing or near-closing odds for the first backtest.
5. Join odds and results by competition, date, and teams.
6. Add pre-match features.
7. Backtest by market and by competition.

## Strong research habits

- Do not mix opening odds and closing odds in the same backtest.
- Do not use post-match information in feature columns.
- Keep European club competitions separate from Super Rugby until enough data exists to tune both.
- Start with one bookmaker or a single consensus price definition before aggregating across books.

## Practical first milestone

Before adding advanced team features, build a clean file with:

- 500 to 2,000 matches,
- true closing odds,
- final scores,
- competition labels.

That is enough to test whether the basic rugby structure filters beat naive betting.
