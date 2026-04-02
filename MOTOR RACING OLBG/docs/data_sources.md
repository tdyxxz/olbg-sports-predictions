# Data Sources

## Recommended split

### Race results and standings

Use Jolpica's Ergast-compatible API for historical F1 race data.

- Base URL: `https://api.jolpi.ca/ergast/f1/`
- Typical endpoints:
  - `/{season}/results.json`
  - `/{season}/qualifying.json`
  - `/{season}/driverStandings.json`
  - `/{season}/{round}/results.json`

Why this source:

- Historical F1 data coverage is broad.
- No API key is required for basic use.
- Endpoint structure is stable for the old Ergast ecosystem.

### Historical odds

Historical bookmaker odds are the harder part. In practice there are two workable paths:

1. Paid historical odds API
2. Manually exported bookmaker or comparison-site data normalized into our schema

Recommended API options to evaluate:

- The Odds API historical endpoints
- Odds API style providers that explicitly expose historical event odds

Important:

- Historical odds access is commonly paid.
- Market naming varies by provider.
- F1 props such as podium and fastest lap may not be available from every source for every season.

## Canonical local data model

We standardize everything into two local files before feature engineering:

- `data\raw\f1_results.csv`
- `data\raw\f1_odds_long.csv`

Then we build the model dataset:

- `data\historical_f1_driver_markets.csv`

## Minimum markets to collect

- `podium_finish`
- `fastest_lap`
- `points_finish`

## Notes on consistency

- Keep odds in decimal format.
- Keep one timestamp policy for the full backtest.
- For pre-race modeling, use the last widely available odds snapshot before the race.
- If you only have qualifying-day odds, keep that consistent across the whole archive.
