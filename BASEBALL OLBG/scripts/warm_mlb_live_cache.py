from __future__ import annotations

import argparse
from datetime import date
from time import perf_counter

from predict_mlb_card import (
    load_daily_schedule,
    load_moneylines,
    load_team_records,
    warm_live_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm MLB live caches for a target date.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--cache-minutes", type=int, default=10, help="Freshness window for live cache artifacts.")
    parser.add_argument("--workers", type=int, default=8, help="Worker count for team and pitcher warmup.")
    args = parser.parse_args()

    season = int(args.date[:4])
    started = perf_counter()

    load_team_records(season, args.date)
    load_team_records(season - 1, f"season_{season - 1}")
    load_moneylines(args.date, args.cache_minutes)
    schedule = load_daily_schedule(args.date, args.cache_minutes)
    dates = schedule.get("dates", [])
    games = dates[0].get("games", []) if dates else []
    pregame_games = [game for game in games if game["status"]["detailedState"] == "Pre-Game"]
    warm_live_inputs(pregame_games, season, args.date, args.workers)

    elapsed = perf_counter() - started
    print(f"Warmed MLB live cache for {args.date}")
    print(f"Pregame games: {len(pregame_games)}")
    print(f"Elapsed seconds: {elapsed:.2f}")


if __name__ == "__main__":
    main()
