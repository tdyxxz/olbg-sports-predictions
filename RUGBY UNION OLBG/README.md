# Rugby Union Profitability Lab

This workspace turns the existing rugby prompt into a backtestable betting model with one goal: profit, not pick volume.

## What is here

- `prompts/rugby_profitability_prompt.md`
  - A rewritten research prompt focused on structured decision inputs, not polished public-facing tips.
- `docs/rugby_model_strategy.md`
  - The betting philosophy, rugby-specific feature set, and profitability filters.
- `data/historical_matches_sample.csv`
  - Sample schema for historical backtesting data.
- `scripts/backtest_rugby.ps1`
  - PowerShell backtester that reads a CSV, scores each market, simulates flat staking, and reports ROI.

## Why this structure

The original text file is useful as domain knowledge, but it is not yet a model. A profitable process needs:

1. Structured historical data.
2. A consistent scoring function.
3. Market entry filters.
4. A backtest that can be rerun after every rule change.

## Data required

At minimum, each historical row should represent one match and include:

- Date
- Competition
- Home team
- Away team
- Closing moneyline odds for both teams
- Closing handicap line and odds
- Closing total line and odds
- Final score
- A compact set of pre-match features known before kickoff

The sample CSV shows the exact column names expected by the script.

## Running the backtest

From this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backtest_rugby.ps1 -CsvPath .\data\historical_matches_sample.csv
```

If your machine has a different PowerShell invocation, use that equivalent command.

## Recommended build order

1. Replace the sample CSV with real historical rugby data.
2. Run the backtest and inspect ROI by market.
3. Tighten filters until the model trades less often but with a stronger edge.
4. Add league-specific tuning after enough data exists for each competition.

## Important note

This model intentionally prefers `SKIP` over action. In rugby betting, profitability usually improves when we:

- avoid forcing moneyline underdogs,
- avoid loose Over bets,
- prioritise handicap spots with structural support,
- and treat weather and team-news disruption as hard filters.
