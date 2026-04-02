# Historical Data Schema

The backtest script expects one row per runner per race in CSV format.

## Required columns

- `race_id`: stable identifier for the race
- `race_date`: race date in `YYYY-MM-DD`
- `dog_name`: runner name
- `track`: venue code or name
- `distance_m`: race distance in metres
- `grade`: race grade such as `A1`, `A3`, `D2`, `OR`
- `trap`: trap number
- `sp_decimal`: decimal starting price
- `finish_pos`: finishing position as an integer

## Optional but useful columns

- `split_time`: sectional or early pace split
- `run_time`: final race time
- `trainer`
- `bend_pos`
- `weight`

## Notes

- Each race should contain all runners if possible.
- `finish_pos = 1` is treated as the winner.
- Use decimal odds. Example: `3/1` should be converted to `4.0`.
- Missing optional columns are allowed; the script will fall back to simpler features.
- Rows must represent actual historical outcomes, not forecasts.

## Minimal example

```csv
race_id,race_date,dog_name,track,distance_m,grade,trap,sp_decimal,finish_pos,split_time,run_time
MONMORE_2025-01-03_18:42,2025-01-03,Swift Aces,Monmore,480,A3,2,3.75,1,4.41,28.72
MONMORE_2025-01-03_18:42,2025-01-03,Rapid Kestrel,Monmore,480,A3,5,4.20,2,4.49,28.90
MONMORE_2025-01-03_18:42,2025-01-03,Blue Cedar,Monmore,480,A3,1,6.00,3,4.55,29.01
```

## Recommended source structure

If you build this from scraped form:

- Keep one raw file with all scraped fields.
- Export one normalized training file that matches this schema.
- Preserve original race timestamps if available, even if the baseline script only needs dates today.
