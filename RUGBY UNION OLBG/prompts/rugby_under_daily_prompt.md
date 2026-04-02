# Rugby Daily Prompt

```text
Evaluate the upcoming rugby union matches below and decide whether each match is:
- UNDER
- AWAY WINNER
- or SKIP

Use only this model:

1. Estimate UNDER model probability from:
- each team's last 5 results
- each team's last 5 points scored
- each team's last 5 points conceded
- each team's last 5 average margin
- each team's recent performance versus market expectation if available
- the competition's recent scoring baseline

2. Estimate AWAY WINNER model probability from:
- home and away implied probabilities from sportsbook odds
- recent win rate
- recent average margin
- recent performance versus market expectation
- home and away venue form

3. Convert the sportsbook odds to implied probabilities.

4. Compute:
- under_edge = under_model_probability - under_implied_probability
- total_line_vs_comp_avg = posted total line - recent competition average total line
- away_edge = away_model_probability - away_implied_probability

5. Recommend UNDER only if all are true:
- under_edge >= 0.07
- total line is between 46.5 and 66.5
- total_line_vs_comp_avg <= 2.0

6. Recommend AWAY WINNER only if all are true:
- competition is Super Rugby
- away_edge >= 0.05
- away odds are between 1.50 and 2.20

7. If neither market qualifies, return SKIP.

Confidence:
- HIGH if under_edge >= 0.10
- MEDIUM if under_edge is between 0.07 and 0.099
- HIGH for AWAY WINNER if away_edge >= 0.10
- MEDIUM for AWAY WINNER if away_edge is between 0.05 and 0.099
- If the relevant edge is below threshold, it must be SKIP

Output exactly this format for each match:

Match: HOME TEAM vs AWAY TEAM
Competition: COMPETITION
Decision: UNDER or AWAY WINNER or SKIP
Confidence: HIGH or MEDIUM or SKIP
Sportsbook Total Line: X.X or N/A
Under Odds: X.XX or N/A
Away Odds: X.XX or N/A
Under Implied Probability: X.XXX or N/A
Away Implied Probability: X.XXX or N/A
Model Under Probability: X.XXX or N/A
Model Away Probability: X.XXX or N/A
Edge: X.XXX
Reasoning: 2-4 concise sentences.

Then finish with:
- Active plays only
- One-line summary of why those matches qualified

Important:
- Do not recommend handicap
- Do not force picks
- Prefer SKIP if data is incomplete or noisy
- Do not mention staking or bankroll

Upcoming matches and odds:
[PASTE MATCHES HERE]
```
