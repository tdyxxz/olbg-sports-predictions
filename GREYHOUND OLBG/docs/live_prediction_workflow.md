# Live Prediction Workflow

This workflow is for daily winner picks using the current profitability rules.

## Current live rule set

- minimum model edge over market: `0.05`
- minimum odds: `2.5`
- maximum odds: `8.0`
- minimum probability gap over second-rated runner: `0.06`

## Required inputs

1. Historical runner dataset in the same schema used for backtesting
2. Upcoming race card with one row per runner

## Upcoming card columns

- `race_id`
- `race_date`
- `race_time`
- `dog_name`
- `track`
- `distance_m`
- `grade`
- `trap`
- `sp_decimal`
- optional:
  - `isp`
  - `split_time`
  - `run_time`
  - `trainer`

## Process

1. Train on all completed historical races before the prediction date.
2. Build the same rolling features for the upcoming runners.
3. Score each runner and normalize probabilities within each race.
4. Rank runners inside each race.
5. Flag only races where the top-rated runner passes the profitability filters.
6. Send the flagged rows into the output prompt for readable daily picks.

## Important guardrail

If the market odds are missing or clearly stale, do not force a selection.
