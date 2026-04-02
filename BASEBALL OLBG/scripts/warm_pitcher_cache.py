from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backtest_moneyline_with_starters import CACHE_DIR, fetch_json


def ensure_schedule_cache(season: int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"schedule_probables_{season}.json"
    if cache_path.exists():
        return cache_path

    payload = fetch_json(
        f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={season}-03-01&endDate={season}-11-30&hydrate=probablePitcher,team"
    )
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return cache_path


def probable_pitcher_ids(season: int) -> set[int]:
    payload = json.loads(ensure_schedule_cache(season).read_text(encoding="utf-8"))
    pitcher_ids: set[int] = set()
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            for side in ("away", "home"):
                team = game["teams"][side]["team"]
                if "name" not in team:
                    continue
                pid = game["teams"][side].get("probablePitcher", {}).get("id")
                if pid:
                    pitcher_ids.add(pid)
    return pitcher_ids


def warm_pitcher_gamelog(season: int, pitcher_id: int) -> str:
    folder = CACHE_DIR / "pitcher_gamelogs"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{season}_{pitcher_id}.json"
    if cache_path.exists():
        return "cached"

    data = fetch_json(
        f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=gameLog&group=pitching&season={season}"
    )
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return "fetched"


def warm_pitcher_season(season: int, pitcher_id: int) -> str:
    folder = CACHE_DIR / "pitcher_season"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{season}_{pitcher_id}.json"
    if cache_path.exists():
        return "cached"

    data = fetch_json(
        f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=season&group=pitching&season={season}"
    )
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return "fetched"


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm MLB pitcher caches for a season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    pitcher_ids = sorted(probable_pitcher_ids(args.season))
    print(f"Found {len(pitcher_ids)} probable pitchers for {args.season}")

    game_log_folder = CACHE_DIR / "pitcher_gamelogs"
    prev_season_folder = CACHE_DIR / "pitcher_season"
    existing_gamelogs = {int(p.stem.split("_")[1]) for p in game_log_folder.glob(f"{args.season}_*.json")}
    existing_prev = {int(p.stem.split("_")[1]) for p in prev_season_folder.glob(f"{args.season - 1}_*.json")}

    missing_gamelogs = [pid for pid in pitcher_ids if pid not in existing_gamelogs]
    missing_prev = [pid for pid in pitcher_ids if pid not in existing_prev]

    print(f"Missing game logs: {len(missing_gamelogs)}")
    print(f"Missing prior-season summaries: {len(missing_prev)}")

    if missing_gamelogs:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(warm_pitcher_gamelog, args.season, pid): pid for pid in missing_gamelogs}
            for index, future in enumerate(as_completed(futures), start=1):
                pid = futures[future]
                future.result()
                if index % 25 == 0 or index == len(futures):
                    print(f"Game logs warmed: {index}/{len(futures)}")

    if missing_prev:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(warm_pitcher_season, args.season - 1, pid): pid for pid in missing_prev}
            for index, future in enumerate(as_completed(futures), start=1):
                pid = futures[future]
                future.result()
                if index % 25 == 0 or index == len(futures):
                    print(f"Prior-season stats warmed: {index}/{len(futures)}")


if __name__ == "__main__":
    main()
