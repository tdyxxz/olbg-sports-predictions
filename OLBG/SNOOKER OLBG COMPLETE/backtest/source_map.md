# Source Map

## Summary

This is the practical status of free historical data for the five target sports.

## Snooker

- Free results/outcomes: `Yes`
- Free historical odds: `Partial`
- Best free sources:
  - [snooker.org results](https://www.snooker.org/res/index.asp?template=22)
  - [Livesport snooker archive](https://www.livesport.com/en/snooker/world/world-championship/archive/)
- Notes:
  - Results are easy to get.
  - Odds may appear on some Livesport event pages, but this is not a clean bulk historical odds feed.

## Rugby Union

- Free results/outcomes: `Yes`
- Free historical odds: `Partial`
- Best free sources:
  - [Livesport rugby union archive](https://www.livesport.com/rugby-union/)
  - Example competitions:
    - [Premiership Rugby archive](https://www.livesport.com/rugby-union/england/premiership-rugby/archive/)
    - [United Rugby Championship archive](https://www.livesport.com/rugby-union/world/united-rugby-championship/archive/)
    - [Rugby Championship archive](https://www.livesport.com/rugby-union/world/rugby-championship/archive/)
- Notes:
  - Competition archive pages are strong for results.
  - Some pages expose odds tabs, but there is no reliable free bulk odds dataset I can confirm.

## Motor Racing

- Free results/outcomes: `Yes`
- Free historical odds: `No reliable free source confirmed`
- Best free sources:
  - [Ergast-compatible F1 API directory page](https://openpublicapis.com/api/ergast-f1)
  - [Livesport Formula 1 results](https://www.livesport.com/en/auto-racing/formula-1/)
- Notes:
  - F1 results are easy.
  - I have not confirmed a free, structured historical bookmaker odds source for motorsport.

## Golf

- Free results/outcomes: `Yes`
- Free historical odds: `No reliable free source confirmed`
- Best free sources:
  - [Livesport golf results](https://www.livesport.com/golf/)
  - Example archive:
    - [The Sentry archive](https://www.livesport.com/golf/pga-tour/the-sentry/archive/)
- Notes:
  - Results and winner history are available.
  - I have not confirmed a free bulk historical odds source for outright, top-6, FRL, and regional markets.

## Greyhounds

- Free results/outcomes: `Yes`
- Free historical odds: `Yes, partial and region-specific`
- Best free sources:
  - [FastTrack Greyhound Racing Victoria](https://fasttrack.grv.org.au/Racing)
  - Example meeting page with prices:
    - [Sandown 10 March 2025](https://fasttrack.grv.org.au/RaceField/ViewRaces/1124029094?raceId=0)
- Notes:
  - FastTrack pages expose race results, prices, and some dividend data.
  - This is the strongest free odds-plus-results source I found among the five sports, but it is not global.

## Practical Recommendation

If we stay fully free:

1. Start with `Greyhounds` for true ROI testing.
2. Use `Motor Racing` for results-based validation only unless we manually add odds.
3. Use `Snooker` and `Rugby Union` for partial ROI testing where odds can be recovered event by event.
4. Treat `Golf` as results-only until better odds data is available.
