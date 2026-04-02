from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd

from backtest_moneyline_with_starters import (
    CACHE_DIR,
    TeamState,
    american_to_probability,
    fetch_json,
    get_pitcher_pre_stats,
    load_historical_games,
    load_schedule_cache,
    starter_score,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


@lru_cache(maxsize=None)
def load_pitcher_hand(pitcher_id: int | None) -> str:
    if not pitcher_id:
        return "R"
    folder = CACHE_DIR / "pitcher_meta"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{pitcher_id}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return str(payload.get("code", "R"))

    data = fetch_json(f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}")
    person = data.get("people", [{}])[0]
    pitch_hand = person.get("pitchHand", {}) or {}
    code = str(pitch_hand.get("code", "R"))
    cache_path.write_text(json.dumps({"code": code}), encoding="utf-8")
    return code


@lru_cache(maxsize=None)
def load_team_previous_splits(team_id: int | None, season: int) -> dict:
    default = {
        "ops_vs_l": 0.720,
        "ops_vs_r": 0.720,
        "avg_vs_l": 0.245,
        "avg_vs_r": 0.245,
        "relief_era": 4.20,
        "relief_whip": 1.32,
        "relief_k9": 8.8,
    }
    if not team_id:
        return default

    folder = CACHE_DIR / "team_splits"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{season}_{team_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    result = default.copy()

    hitting = fetch_json(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting&sitCodes=vr,vl&season={season}"
    )
    for block in hitting.get("stats", []):
        for split in block.get("splits", []):
            code = split.get("split", {}).get("code")
            stat = split.get("stat", {}) or {}
            if code == "vl":
                result["ops_vs_l"] = float(stat.get("ops") or result["ops_vs_l"])
                result["avg_vs_l"] = float(stat.get("avg") or result["avg_vs_l"])
            elif code == "vr":
                result["ops_vs_r"] = float(stat.get("ops") or result["ops_vs_r"])
                result["avg_vs_r"] = float(stat.get("avg") or result["avg_vs_r"])

    pitching = fetch_json(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=pitching&sitCodes=rp&season={season}"
    )
    for block in pitching.get("stats", []):
        for split in block.get("splits", []):
            if split.get("split", {}).get("code") != "rp":
                continue
            stat = split.get("stat", {}) or {}
            result["relief_era"] = float(stat.get("era") or result["relief_era"])
            result["relief_whip"] = float(stat.get("whip") or result["relief_whip"])
            result["relief_k9"] = float(stat.get("strikeoutsPer9Inn") or result["relief_k9"])

    cache_path.write_text(json.dumps(result), encoding="utf-8")
    return result


def bullpen_score(splits: dict) -> float:
    return (
        ((5.0 - float(splits["relief_era"])) / 2.0)
        + (1.35 - float(splits["relief_whip"]))
        + ((float(splits["relief_k9"]) - 8.0) / 4.0)
    ) / 3.0


def build_rows(start_season: int, end_season: int) -> list[dict]:
    games = load_historical_games(start_season, end_season)
    schedule_caches = {s: load_schedule_cache(s) for s in range(start_season, end_season + 1)}
    team_states: dict[str, TeamState] = defaultdict(TeamState)
    rows: list[dict] = []

    for game in games:
        season = game["season"]
        away_state = team_states[game["away_team"]]
        home_state = team_states[game["home_team"]]
        if away_state.season != season:
            away_state.reset(season)
        if home_state.season != season:
            home_state.reset(season)

        if away_state.games_seen() >= 8 and home_state.games_seen() >= 8:
            starter_info = schedule_caches[season].get((game["date"], game["away_team"], game["home_team"]), {})
            away_team_id = starter_info.get("away_team_id")
            home_team_id = starter_info.get("home_team_id")
            away_pitcher_id = starter_info.get("away_pitcher_id")
            home_pitcher_id = starter_info.get("home_pitcher_id")
            away_starter = get_pitcher_pre_stats(starter_info.get("away_pitcher_id"), season, game["date"])
            home_starter = get_pitcher_pre_stats(starter_info.get("home_pitcher_id"), season, game["date"])
            away_pitcher_hand = load_pitcher_hand(away_pitcher_id)
            home_pitcher_hand = load_pitcher_hand(home_pitcher_id)
            away_prev = load_team_previous_splits(away_team_id, season - 1)
            home_prev = load_team_previous_splits(home_team_id, season - 1)
            away_bullpen_score = bullpen_score(away_prev)
            home_bullpen_score = bullpen_score(home_prev)
            away_ops_vs_home_hand = away_prev["ops_vs_l"] if home_pitcher_hand == "L" else away_prev["ops_vs_r"]
            home_ops_vs_away_hand = home_prev["ops_vs_l"] if away_pitcher_hand == "L" else home_prev["ops_vs_r"]
            away_avg_vs_home_hand = away_prev["avg_vs_l"] if home_pitcher_hand == "L" else away_prev["avg_vs_r"]
            home_avg_vs_away_hand = home_prev["avg_vs_l"] if away_pitcher_hand == "L" else home_prev["avg_vs_r"]

            away_open_prob = american_to_probability(game["open_away"])
            home_open_prob = american_to_probability(game["open_home"])
            market_away_prob = away_open_prob / (away_open_prob + home_open_prob)

            rows.append(
                {
                    "date": game["date"],
                    "season": season,
                    "away_team": game["away_team_display"],
                    "home_team": game["home_team_display"],
                    "away_win": int(game["away_score"] > game["home_score"]),
                    "away_open_odds": game["open_away"],
                    "home_open_odds": game["open_home"],
                    "away_close_odds": game["close_away"],
                    "home_close_odds": game["close_home"],
                    "market_away_prob": market_away_prob,
                    "away_recent_win_pct": away_state.recent_win_pct(),
                    "home_recent_win_pct": home_state.recent_win_pct(),
                    "away_recent_rd_pg": away_state.recent_run_diff_pg(),
                    "home_recent_rd_pg": home_state.recent_run_diff_pg(),
                    "away_season_win_pct": away_state.season_win_pct(),
                    "home_season_win_pct": home_state.season_win_pct(),
                    "away_season_rd_pg": away_state.season_run_diff_pg(),
                    "home_season_rd_pg": home_state.season_run_diff_pg(),
                    "away_road_win_pct": away_state.away_win_pct(),
                    "home_home_win_pct": home_state.home_win_pct(),
                    "away_road_rd_pg": away_state.away_run_diff_pg(),
                    "home_home_rd_pg": home_state.home_run_diff_pg(),
                    "away_starter_era": away_starter.era,
                    "home_starter_era": home_starter.era,
                    "away_starter_whip": away_starter.whip,
                    "home_starter_whip": home_starter.whip,
                    "away_starter_k9": away_starter.k9,
                    "home_starter_k9": home_starter.k9,
                    "away_starter_recent3_era": away_starter.recent3_era,
                    "home_starter_recent3_era": home_starter.recent3_era,
                    "away_starter_score": starter_score(away_starter),
                    "home_starter_score": starter_score(home_starter),
                    "recent_win_edge": away_state.recent_win_pct() - home_state.recent_win_pct(),
                    "recent_rd_edge": away_state.recent_run_diff_pg() - home_state.recent_run_diff_pg(),
                    "season_win_edge": away_state.season_win_pct() - home_state.season_win_pct(),
                    "season_rd_edge": away_state.season_run_diff_pg() - home_state.season_run_diff_pg(),
                    "venue_win_edge": away_state.away_win_pct() - home_state.home_win_pct(),
                    "venue_rd_edge": away_state.away_run_diff_pg() - home_state.home_run_diff_pg(),
                    "starter_edge": starter_score(away_starter) - starter_score(home_starter),
                    "away_pitcher_hand": away_pitcher_hand,
                    "home_pitcher_hand": home_pitcher_hand,
                    "away_prev_ops_vs_hand": away_ops_vs_home_hand,
                    "home_prev_ops_vs_hand": home_ops_vs_away_hand,
                    "away_prev_avg_vs_hand": away_avg_vs_home_hand,
                    "home_prev_avg_vs_hand": home_avg_vs_away_hand,
                    "prev_ops_hand_edge": away_ops_vs_home_hand - home_ops_vs_away_hand,
                    "prev_avg_hand_edge": away_avg_vs_home_hand - home_avg_vs_away_hand,
                    "away_prev_relief_era": away_prev["relief_era"],
                    "home_prev_relief_era": home_prev["relief_era"],
                    "away_prev_relief_whip": away_prev["relief_whip"],
                    "home_prev_relief_whip": home_prev["relief_whip"],
                    "away_prev_relief_k9": away_prev["relief_k9"],
                    "home_prev_relief_k9": home_prev["relief_k9"],
                    "away_prev_bullpen_score": away_bullpen_score,
                    "home_prev_bullpen_score": home_bullpen_score,
                    "prev_bullpen_edge": away_bullpen_score - home_bullpen_score,
                }
            )

        away_state.record(game["away_score"], game["home_score"], is_home=False)
        home_state.record(game["home_score"], game["away_score"], is_home=True)

    return rows


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_rows(2023, 2025)
    df = pd.DataFrame(rows)

    csv_path = OUTPUT_DIR / "moneyline_feature_dataset_v2_2023_2025.csv"
    json_path = OUTPUT_DIR / "moneyline_feature_dataset_v2_2023_2025.json"
    summary_path = OUTPUT_DIR / "moneyline_feature_dataset_v2_summary.json"

    df.to_csv(csv_path, index=False)
    json_path.write_text(df.to_json(orient="records", indent=2), encoding="utf-8")

    summary = {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "seasons": sorted(df["season"].unique().tolist()),
        "away_win_rate": float(df["away_win"].mean()) if len(df) else 0.0,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(csv_path)


if __name__ == "__main__":
    main()
