# Prompt Usage

Use `golf_top10_prediction_prompt_v2.txt` when you want ChatGPT to generate upcoming-event Top 10 Finish bets.

## Best way to use it

Paste the prompt first, then add:

- the tournament name
- the sportsbook or odds source you want prioritized
- the list of available Top 10 prices if you already have them
- any extra constraints such as `max 2 picks` or `skip if no medium-confidence edge`

## Recommended add-on instruction

After the main prompt, add this block:

```text
Upcoming event: <TOURNAMENT NAME>
Objective: Find only profitable Top 10 Finish bets for this event.
Use current publicly available prices.
Do not recommend more than 2 bets unless there are 3 clearly mispriced options.
If the market is efficient, output SKIP.
```

## Example add-on

```text
Upcoming event: Valspar Championship
Objective: Find only profitable Top 10 Finish bets for this event.
Use current publicly available prices.
Prioritize DraftKings and FanDuel if both are available.
Do not recommend more than 2 bets unless there are 3 clearly mispriced options.
If the market is efficient, output SKIP.
```

## Practical guidance

- Keep the market scope narrow.
- Ask for Top 10 only.
- Explicitly allow SKIP.
- Ask for price/value reasoning every time.
- Avoid asking for long cards or entertainment picks.
