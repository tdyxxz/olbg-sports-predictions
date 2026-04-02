from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from backtest_moneyline_with_starters import (
    TeamState,
    american_to_probability,
    get_pitcher_pre_stats,
    load_historical_games,
    load_schedule_cache,
    model_probability,
    settle_american_bet,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


def build_bet_rows(start_season: int, end_season: int) -> list[dict]:
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
            away_starter = get_pitcher_pre_stats(starter_info.get("away_pitcher_id"), season, game["date"])
            home_starter = get_pitcher_pre_stats(starter_info.get("home_pitcher_id"), season, game["date"])
            away_prob = model_probability(
                away_state,
                home_state,
                away_starter,
                home_starter,
                game["open_away"],
                game["open_home"],
            )
            home_prob = 1.0 - away_prob
            away_edge = away_prob - american_to_probability(game["open_away"])
            home_edge = home_prob - american_to_probability(game["open_home"])

            if away_edge >= home_edge:
                rows.append(
                    {
                        "season": season,
                        "edge": away_edge,
                        "odds": game["open_away"],
                        "won": game["away_score"] > game["home_score"],
                        "profit": settle_american_bet(game["open_away"], game["away_score"] > game["home_score"]),
                    }
                )
            else:
                rows.append(
                    {
                        "season": season,
                        "edge": home_edge,
                        "odds": game["open_home"],
                        "won": game["home_score"] > game["away_score"],
                        "profit": settle_american_bet(game["open_home"], game["home_score"] > game["away_score"]),
                    }
                )

        away_state.record(game["away_score"], game["home_score"])
        home_state.record(game["home_score"], game["away_score"])

    return rows


def regime_match(row: dict, min_edge: float, band_name: str) -> bool:
    if row["edge"] < min_edge:
        return False
    odds = row["odds"]
    if band_name == "all":
        return True
    if band_name == "heavy_favorites":
        return odds <= -300
    if band_name == "mid_favorites":
        return -199 <= odds <= -110
    if band_name == "short_underdogs":
        return 100 < odds <= 150
    if band_name == "heavy_or_short_dog":
        return odds <= -300 or (100 < odds <= 150)
    if band_name == "favorites_200_plus_or_short_dog":
        return odds <= -200 or (100 < odds <= 150)
    return False


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"bets": 0, "profit": 0.0, "roi": 0.0, "win_rate": 0.0}
    profit = sum(r["profit"] for r in rows)
    return {
        "bets": len(rows),
        "profit": profit,
        "roi": profit / len(rows),
        "win_rate": mean(1.0 if r["won"] else 0.0 for r in rows),
    }


def main() -> None:
    rows = build_bet_rows(2023, 2025)
    band_names = [
        "all",
        "heavy_favorites",
        "mid_favorites",
        "short_underdogs",
        "heavy_or_short_dog",
        "favorites_200_plus_or_short_dog",
    ]
    thresholds = [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25]

    results = []
    for band in band_names:
        for threshold in thresholds:
            overall = [r for r in rows if regime_match(r, threshold, band)]
            overall_summary = summarize(overall)
            by_year = {}
            positive_years = 0
            for season in (2023, 2024, 2025):
                season_rows = [r for r in overall if r["season"] == season]
                season_summary = summarize(season_rows)
                by_year[str(season)] = season_summary
                if season_summary["bets"] > 0 and season_summary["roi"] > 0:
                    positive_years += 1

            results.append(
                {
                    "band": band,
                    "min_edge": threshold,
                    "overall": overall_summary,
                    "positive_years": positive_years,
                    "by_year": by_year,
                }
            )

    results.sort(
        key=lambda item: (
            item["positive_years"],
            item["overall"]["roi"],
            item["overall"]["profit"],
            item["overall"]["bets"],
        ),
        reverse=True,
    )

    out_path = OUTPUT_DIR / "moneyline_regime_search.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    top = results[:20]
    print(json.dumps(top, indent=2))
    print(f"Saved full results to {out_path}")


if __name__ == "__main__":
    main()
