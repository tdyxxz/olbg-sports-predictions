# Rugby Union Profitability Research Prompt

Use this prompt to generate structured pre-match inputs for the backtester and live model. The target is expected value and long-run profit, not content quality or pick frequency.

## Task

For each rugby union match, produce structured pre-match ratings for the three supported markets:

- match winner
- underdog handicap
- total points

Do not write public betting tips first. Build the data record first.

## Required output format

Return exactly one JSON object per match with these keys:

```json
{
  "match_date": "YYYY-MM-DD",
  "competition": "string",
  "home_team": "string",
  "away_team": "string",
  "home_moneyline_decimal": 0.0,
  "away_moneyline_decimal": 0.0,
  "handicap_team": "HOME_OR_AWAY",
  "handicap_line": 0.0,
  "handicap_odds_decimal": 0.0,
  "total_line": 0.0,
  "over_odds_decimal": 0.0,
  "under_odds_decimal": 0.0,
  "home_recent_win_rate": 0.0,
  "away_recent_win_rate": 0.0,
  "home_recent_avg_margin": 0.0,
  "away_recent_avg_margin": 0.0,
  "home_set_piece_rating": 0.0,
  "away_set_piece_rating": 0.0,
  "home_goal_kicking_rating": 0.0,
  "away_goal_kicking_rating": 0.0,
  "weather_severity": 0.0,
  "ref_penalty_bias": 0.0,
  "home_rest_days": 0,
  "away_rest_days": 0,
  "travel_fatigue_away": 0.0,
  "international_absence_home": 0.0,
  "international_absence_away": 0.0,
  "competition_pace_factor": 0.0,
  "home_ats_cover_rate": 0.0,
  "away_ats_cover_rate": 0.0,
  "notes": "short internal summary"
}
```

## Rating scales

Use normalised scales so the backtester can score consistently:

- Ratings from `0` to `100` for set piece and goal kicking.
- Rates from `0.0` to `1.0` for win rates and ATS cover rates.
- `weather_severity` from `0.0` to `1.0`
  - `0.0` means ideal scoring conditions.
  - `1.0` means heavy weather likely to suppress attack.
- `ref_penalty_bias` from `-1.0` to `1.0`
  - negative means flow-friendly,
  - positive means penalty-heavy and stop-start.
- `travel_fatigue_away` from `0.0` to `1.0`
- `international_absence_*` from `0.0` to `1.0`
- `competition_pace_factor` from `-1.0` to `1.0`
  - negative means slower-than-average scoring environment,
  - positive means faster-than-average scoring environment.

## Rugby-specific priorities

Weight these more than generic team strength:

1. Set-piece control
2. Goal-kicking reliability
3. Weather
4. Squad disruption during international periods
5. Margin resilience for underdogs
6. Competition-specific scoring baseline

## Market logic

### Match winner

Look for:

- clear structural edge,
- sustainable territory edge,
- and a fair or generous price.

### Underdog handicap

Prefer this market when the underdog:

- can remain competitive in the scrum and lineout,
- kicks goals reliably,
- and has avoided recent heavy defeats.

### Total points

Prefer Under when:

- weather is adverse,
- referee profile is whistle-heavy,
- teams are tactical and field-position driven,
- or the competition baseline is slow.

Prefer Over only with strong pace and clean conditions.

## Hard rules

- It is acceptable to recommend no bet.
- Do not force a pick in every match.
- Never treat descriptive confidence as proof of value.
- If the market price looks efficient, pass.
