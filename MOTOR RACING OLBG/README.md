# F1 Profitability Model

This workspace turns the starting prompt into a backtestable F1 betting workflow focused on profitability rather than pick rate.

## What this system does

- Models three driver markets on a per-driver, per-race basis:
  - `podium_finish` (`top 3`)
  - `fastest_lap`
  - `points_finish` (`top 10`)
- Uses historical bookmaker odds and race outcomes to estimate probabilities.
- Applies profitability gates so a pick is only bet when the model price beats the market by a required margin.
- Backtests each market with walk-forward evaluation to reduce look-ahead bias.

## Files

- [MOTOR RACING.txt](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\MOTOR RACING.txt)
  Starting prompt/source notes.
- [prompts\f1_profitability_prompt.txt](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\prompts\f1_profitability_prompt.txt)
  Production prompt for turning model outputs into race-weekend betting notes.
- [strategy\f1_profit_strategy.md](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\strategy\f1_profit_strategy.md)
  Profit-first framework adapted from the strongest rugby-style ideas.
- [data\historical_f1_driver_markets.csv](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\data\historical_f1_driver_markets.csv)
  Historical dataset template. Replace sample rows with real historical data.
- [src\f1_backtest.py](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\src\f1_backtest.py)
  Pure-Python walk-forward trainer and backtester.
- [src\fetch_jolpica_results.py](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\src\fetch_jolpica_results.py)
  Pulls historical F1 race and qualifying results from Jolpica into a normalized CSV.
- [src\normalize_odds.py](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\src\normalize_odds.py)
  Converts raw odds exports into a canonical long-format file.
- [src\build_f1_dataset.py](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\src\build_f1_dataset.py)
  Joins normalized results and odds into the modeling dataset.
- [src\fetch_formula1_betting_guides.py](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\src\fetch_formula1_betting_guides.py)
  Scrapes official Formula1.com betting-guide tables into a structured historical odds CSV.
- [config\market_configs.json](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\config\market_configs.json)
  Market-specific feature lists and bet thresholds.
- [docs\data_sources.md](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\docs\data_sources.md)
  Notes on practical source options for results and historical odds.

## Data layout

Each row is one driver in one race. Required groups:

- Race metadata: season, round, date, circuit
- Driver/team identity
- Pre-race features only
- Decimal odds for each market
- Outcome labels for each market

Important:

- Do not use post-race variables as features.
- For qualifying-based features, use the final confirmed starting grid only if the bet is placed after qualifying.
- Keep odds timestamp-consistent. Closing odds are fine for backtests if used consistently.

## Suggested workflow

1. Fetch normalized race results:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\fetch_jolpica_results.py' --start-season 2019 --end-season 2025
```

2. Put raw odds exports into [data\incoming\odds_export_template.csv](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\data\incoming\odds_export_template.csv) format, then normalize:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\normalize_odds.py' --input '.\data\incoming\odds_export_template.csv'
```

3. Build the model dataset:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\build_f1_dataset.py'
```

4. Run the backtester to get probability calibration and ROI by market.
5. Adjust thresholds in [config\market_configs.json](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\config\market_configs.json), not by cherry-picking races.
6. Use the prompt file to convert model outputs into a short betting card.

## Official F1 Betting-Guide Archive

To gather the official Formula1.com betting-guide odds archive:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\fetch_formula1_betting_guides.py' --results-reference '.\data\raw\f1_results.csv'
```

This currently captures:

- `podium_finish`
- `points_finish`
- `top_6_finish`
- `race_win`
- `qualifying_fastest`

Important:

- Official F1 betting guides give us strong historical coverage for podium and top-10 style markets.
- They do not appear to provide a consistent fastest-lap archive, so that market will need a second source.

## Run

Example:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\f1_backtest.py' --data '.\data\historical_f1_driver_markets.csv'
```

Optional flags:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\f1_backtest.py' --data '.\data\historical_f1_driver_markets.csv' --bankroll 1000 --min-train-races 25
```

## Current limitation

The included CSV contains sample rows only. The model logic is ready, but profitability cannot be trusted until we load real historical odds and outcomes.

## Current focus

The active profitability focus is now:

- `podium_finish`
- `fastest_lap`

The `points_finish` market is still available in the broader pipeline, but it is currently deprioritized because historical odds coverage is much thinner.

## Timing discipline

The active production workflow is now strictly `post-qualifying only`.

That means:

- Use the final confirmed starting grid.
- Use odds captured after qualifying, not before.
- Do not mix pre-qualifying odds with post-qualifying grid positions.

If those timing windows are mixed, the model can show false edge and the backtest becomes misleading.

## Profit tuning

To sweep profitability thresholds for the two active markets:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\tune_profit_markets.py' --data '.\data\historical_f1_driver_markets_from_guides_2020_2025.csv' --config '.\config\market_configs_profit_focus.json'
```

This writes a sortable summary to:

- [data\analysis\profit_market_sweep.csv](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\data\analysis\profit_market_sweep.csv)

## Production race card

Prepare the next race in:

- [data\incoming\upcoming_race_template.csv](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\data\incoming\upcoming_race_template.csv)

Important:

- This template is `post-qualifying only`.
- Do not run the production race card before the grid is finalized.
- The generator now validates that `grid_position` is populated for every driver.

Then generate the active race card:

```powershell
& 'C:\Users\AI AGENT\AppData\Local\Programs\Python\Python312\python.exe' '.\src\generate_race_card.py' --history '.\data\historical_f1_driver_markets_from_guides_2020_2025.csv' --upcoming '.\data\incoming\upcoming_race_template.csv' --config '.\config\market_configs_profit_focus.json'
```

Outputs:

- [outputs\race_card_selections.csv](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\outputs\race_card_selections.csv)
- [outputs\race_card_selections.json](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\outputs\race_card_selections.json)
- [outputs\race_card_report.md](C:\Users\AI AGENT\Desktop\MOTOR RACING OLBG\outputs\race_card_report.md)
