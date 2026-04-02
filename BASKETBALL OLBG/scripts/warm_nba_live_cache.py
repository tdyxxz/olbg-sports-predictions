from __future__ import annotations

import argparse
from datetime import date
from time import perf_counter

from predict_nba_card import load_daily_scoreboard, warm_live_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm NBA live caches for a target date.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--cache-minutes", type=int, default=10, help="Freshness window for live cache artifacts.")
    parser.add_argument("--workers", type=int, default=8, help="Worker count for recent-form warmup.")
    args = parser.parse_args()

    started = perf_counter()
    scoreboard = load_daily_scoreboard(args.date, args.cache_minutes)
    events = scoreboard.get("events", [])
    pregame_events = [event for event in events if event.get("status", {}).get("type", {}).get("state") == "pre"]
    warm_live_inputs(pregame_events, args.date, args.cache_minutes, args.workers)
    elapsed = perf_counter() - started

    print(f"Warmed NBA live cache for {args.date}")
    print(f"Pregame games: {len(pregame_events)}")
    print(f"Elapsed seconds: {elapsed:.2f}")


if __name__ == "__main__":
    main()
