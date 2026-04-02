# Rugby Union Model Strategy

## Objective

Build a rugby union betting model that maximises long-run ROI, even if that means very few bets.

## Core principle

The model should not try to predict every match equally well. It should only bet when the market is most likely to have mispriced rugby-specific structure.

## Markets to attack

In order of preference:

1. Underdog handicap
2. Match winner
3. Totals

That ordering is intentional:

- Rugby underdogs can cover through penalty accumulation and tactical kicking even when they lose.
- Match winners can be profitable, but only when structural dominance and price agree.
- Totals are highly sensitive to weather, referee style, and competition scoring environment, so they need tighter filters.

## Rugby-specific edges

These are the highest-value pre-match factors from the starter prompt:

- Set-piece strength gap
- Goal-kicking reliability gap
- Weather suppression risk
- International window disruption
- Travel and short-rest fatigue
- Competition scoring environment
- Referee penalty tendency
- Recent margin profile, not just win-loss record

## Profitability-first entry logic

The model should not simply take the highest raw score. It should pass a trade only if it clears both a quality threshold and a price/value threshold.

### Match winner

Back only when all are true:

- Model score is strong.
- Team has a clear set-piece or territory edge.
- Price is not too short.
- No major weather or availability contradiction.

Avoid:

- favourites below roughly 1.33 decimal unless the model edge is exceptional,
- underdog moneylines without a credible set-piece and kicking route to win,
- clubs weakened by international absences.

### Underdog handicap

This is the primary market because rugby scoring allows non-try accumulation.

Back only when all are true:

- underdog is competitive in set-piece terms,
- average recent losing margin is controlled,
- goal-kicking is reliable,
- favourite has either fatigue, travel, weather drag, or squad disruption,
- line sits in a moderate cover range rather than an extreme spread.

Avoid:

- repeated blowout teams,
- weak-kicking underdogs,
- underdogs whose scrum is likely to collapse under pressure.

### Totals

Under is usually the more stable side in rugby when the environment is adverse.

Back only when:

- the line is elevated for the competition,
- weather is negative,
- both teams have defensive or kicking-first profiles,
- or the referee profile is likely to break attacking rhythm.

Over should be rarer and needs:

- fast conditions,
- high-tempo teams,
- weak defensive structure,
- and a line that has not already fully priced in the attacking environment.

## Competition adjustments

Baseline totals and aggression should vary by competition:

- Top 14 and Premiership: lean lower scoring and more attritional.
- URC: mixed environment, more team-specific.
- Super Rugby: more open, faster, and more Over-capable.
- Test rugby: motivation and squad quality matter more than domestic form alone.

## Suggested modelling workflow

1. Start with rule-based scores from rugby knowledge.
2. Convert those scores to estimated probabilities.
3. Compare those probabilities to implied bookmaker probabilities.
4. Bet only if edge exceeds a minimum threshold.
5. Track ROI, hit rate, average odds, and max drawdown by market.

## Features to collect historically

- `home_recent_win_rate`
- `away_recent_win_rate`
- `home_recent_avg_margin`
- `away_recent_avg_margin`
- `home_set_piece_rating`
- `away_set_piece_rating`
- `home_goal_kicking_rating`
- `away_goal_kicking_rating`
- `weather_severity`
- `ref_penalty_bias`
- `home_rest_days`
- `away_rest_days`
- `travel_fatigue_away`
- `international_absence_home`
- `international_absence_away`
- `competition_pace_factor`
- `home_ats_cover_rate`
- `away_ats_cover_rate`

## Metrics that matter

Judge changes by:

- ROI
- Profit in units
- Closing-line hit rate by market
- Average odds of winners and losers
- Maximum drawdown
- Number of bets

Never judge the model by win percentage alone.
