# F1 Profitability Strategy

## Objective

The goal is not to predict every race correctly. The goal is to find repeatable situations where the implied probability in the market is lower than the model's estimate by enough margin to overcome error and variance.

## Rugby ideas worth keeping

These ideas transfer well from profitable rugby-style betting workflows:

- Price sensitivity matters more than raw pick accuracy.
- Fewer bets is usually better than forcing action every event.
- Market-by-market specialization beats one blended "best bet" model.
- Walk-forward testing is more honest than fitting on the full history.
- Correlated exposure should be capped.

## Rugby ideas that need adaptation for F1

F1 is much more structured than rugby. Results are heavily shaped by car strength, qualifying position, circuit fit, and reliability. Because of that:

- We should model by driver-market row, not by race winner alone.
- Grid position and teammate-relative pace matter more than broad form.
- Fastest lap is a strategy market, not just a pace market.
- Points finish is often a team-reliability and clean-race market.

## Market definitions

### 1. Podium finish

Target:

- `1` if the driver finished in the top 3.
- `0` otherwise.

Most useful features:

- Starting grid position
- Recent average finish
- Recent average qualifying position
- Teammate qualifying delta
- Team rolling points
- Track history
- Reliability rate
- Constructor strength

Profit rule:

- Bet only if model edge is clearly positive and the driver is not already overexposed through another strongly correlated market.

### 2. Fastest lap

Target:

- `1` if the driver recorded fastest lap.
- `0` otherwise.

Most useful features:

- Starting grid position
- Recent fastest-lap rate
- Team pace ranking
- Pit stop aggressiveness proxy
- Safety car likelihood proxy
- Tyre degradation/circuit profile
- Probability the driver finishes with free-stop margin

Profit rule:

- This market should be extremely selective.
- Skip when the candidate would likely be trapped in traffic or unable to pit late.
- Skip when market prices are too short.

### 3. Points finish

Target:

- `1` if the driver finished in the top 10.
- `0` otherwise.

Most useful features:

- Starting grid position
- Rolling points finishes
- Team reliability rate
- Recent overtaking performance
- Track overtaking difficulty
- Upgrade/form trend
- Constructor midfield strength

Profit rule:

- This will likely become the highest-volume and most stable market.
- Still require a probability edge over market price.

## Profit-first betting rules

- Never bet because the model likes a driver. Bet only because the model price beats the market price.
- Use decimal odds and convert them to implied probability: `1 / odds`.
- Require both:
  - Positive expected value
  - A minimum edge buffer, because model error is real
- Cap bets per race weekend.
- Cap one bet per driver unless historical testing proves stacked positions are worthwhile.
- Review profit by market separately.

## Validation rules

- Train only on races that occurred before the evaluated race.
- Report:
  - Bets placed
  - Hit rate
  - Average model probability
  - Average market implied probability
  - ROI
  - Profit by season
- Tune thresholds only on older history, then freeze and test on the newest season.

## Practical starting assumptions

- Podium market will usually need a higher minimum price edge because it is concentrated among a few elite drivers.
- Fastest lap may have the best occasional edges but also the sparsest signal.
- Points finish is likely the most scalable market for real bankroll deployment.

## What to improve next

- Add bookmaker line snapshots, not just one closing price.
- Add weather, penalties, and sprint-weekend flags.
- Add constructor and teammate context features from prior races only.
- Calibrate probabilities after training if the raw model is overconfident.
