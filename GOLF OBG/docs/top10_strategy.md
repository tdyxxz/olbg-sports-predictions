# Top-10 Strategy Notes

## Objective

Maximize long-run profitability in the `top 10 finish` market only.

This means the model should prefer:

- Fewer bets with stronger edge.
- Repeatable drivers of top-10 probability.
- Stable player profiles over one-week noise.

It should avoid:

- Forcing bets because a tournament is on the board.
- Chasing big prices without enough base probability.
- Treating winner-style upside as the same thing as top-10 reliability.

## Rugby ideas that transfer well

These are the rugby-style principles that still work here:

- Market specialization beats broad-card coverage.
- Price sensitivity matters more than picking "good players."
- Skip discipline is a real edge.
- Backtesting should be done in time order.
- Closing line value is a useful quality check even before profit fully stabilizes.

## Features that matter more for top-10 than outright winners

For a top-10 model, prioritize:

- Recent top-10 rate.
- Recent made-cut rate.
- Recent SG approach.
- Recent SG tee-to-green.
- Total SG trend.
- Course history top-10 rate.
- Course fit score.
- World-rank quality band.

Use with lighter weight:

- Putting.
- Win recency.
- Narrative sentiment.
- One-week hot streaks.

## Profitability guardrails

- Default max bets per event: `2`
- Default minimum edge: `4%`
- Default minimum model probability: `10%`
- Default odds band: `2.00` to `8.00`
- Prefer midrange odds over very short or very long prices.
- Do not bet multiple weakly differentiated players from the same event.

## Data design

Build one row per player-event with only information known before the event starts.

Minimum fields:

- event identifiers and date
- player name
- opening and closing top-10 odds
- top-10 result
- pre-tournament recent-form features
- pre-tournament strokes-gained features
- pre-tournament course-fit and course-history features

Best shortcut:

- Use archived sportsbook `top_10` odds plus archived DataGolf pre-tournament `top_10` probabilities.

That gives a clean model-vs-market backtest immediately, even before we finish a full custom feature pipeline.

## Backtest discipline

- Sort by event date.
- Avoid mixing future information into earlier rows.
- Split train/test chronologically, not randomly.
- Review ROI by year, tour, odds band, and edge bucket.
- Prefer settings that stay profitable across slices, not just overall.

## Prompt discipline

The prompt should not be asked to "find winners" or "write impressive tips."

It should:

- score only top-10 probability drivers
- compare that estimate against book price
- skip when edge is thin
- cap selections per event
- explain the pick briefly without inventing certainty
