from __future__ import annotations

import argparse
import bisect
import json
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = BASE_DIR / "data" / "historical" / "mlb_odds_dataset.json"
CACHE_DIR = BASE_DIR / "data" / "historical" / "cache"
OUTPUT_DIR = BASE_DIR / "outputs"
STATS_API = "https://statsapi.mlb.com/api/v1"
SESSION = requests.Session()


def fetch_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=60)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def normalize_team_name(name: str) -> str:
    return (
        name.lower()
        .replace("st. ", "st ")
        .replace("d-backs", "diamondbacks")
        .strip()
    )


def american_to_probability(odds: int) -> float:
    if odds == 0:
        return 0.0
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)


def probability_to_logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def logit_to_probability(logit: float) -> float:
    return 1 / (1 + math.exp(-logit))


def settle_american_bet(odds: int, won: bool) -> float:
    if not won:
        return -1.0
    if odds > 0:
        return odds / 100
    return 100 / (-odds)


@dataclass
class TeamState:
    season: int | None = None
    season_wins: int = 0
    season_losses: int = 0
    season_runs_for: int = 0
    season_runs_against: int = 0
    home_wins: int = 0
    home_losses: int = 0
    home_runs_for: int = 0
    home_runs_against: int = 0
    away_wins: int = 0
    away_losses: int = 0
    away_runs_for: int = 0
    away_runs_against: int = 0
    recent_results: deque[tuple[bool, int]] | None = None

    def __post_init__(self) -> None:
        if self.recent_results is None:
            self.recent_results = deque(maxlen=10)

    def reset(self, season: int) -> None:
        self.season = season
        self.season_wins = 0
        self.season_losses = 0
        self.season_runs_for = 0
        self.season_runs_against = 0
        self.home_wins = 0
        self.home_losses = 0
        self.home_runs_for = 0
        self.home_runs_against = 0
        self.away_wins = 0
        self.away_losses = 0
        self.away_runs_for = 0
        self.away_runs_against = 0
        self.recent_results = deque(maxlen=10)

    def season_win_pct(self) -> float:
        games = self.season_wins + self.season_losses
        return self.season_wins / games if games else 0.5

    def season_run_diff_pg(self) -> float:
        games = self.season_wins + self.season_losses
        if not games:
            return 0.0
        return (self.season_runs_for - self.season_runs_against) / games

    def recent_win_pct(self) -> float:
        if not self.recent_results:
            return 0.5
        return sum(1 for won, _ in self.recent_results if won) / len(self.recent_results)

    def recent_run_diff_pg(self) -> float:
        if not self.recent_results:
            return 0.0
        return sum(diff for _, diff in self.recent_results) / len(self.recent_results)

    def home_win_pct(self) -> float:
        games = self.home_wins + self.home_losses
        return self.home_wins / games if games else 0.5

    def home_run_diff_pg(self) -> float:
        games = self.home_wins + self.home_losses
        if not games:
            return 0.0
        return (self.home_runs_for - self.home_runs_against) / games

    def away_win_pct(self) -> float:
        games = self.away_wins + self.away_losses
        return self.away_wins / games if games else 0.5

    def away_run_diff_pg(self) -> float:
        games = self.away_wins + self.away_losses
        if not games:
            return 0.0
        return (self.away_runs_for - self.away_runs_against) / games

    def games_seen(self) -> int:
        return self.season_wins + self.season_losses

    def record(self, runs_for: int, runs_against: int, is_home: bool | None = None) -> None:
        won = runs_for > runs_against
        if won:
            self.season_wins += 1
        else:
            self.season_losses += 1
        self.season_runs_for += runs_for
        self.season_runs_against += runs_against
        if is_home is True:
            if won:
                self.home_wins += 1
            else:
                self.home_losses += 1
            self.home_runs_for += runs_for
            self.home_runs_against += runs_against
        elif is_home is False:
            if won:
                self.away_wins += 1
            else:
                self.away_losses += 1
            self.away_runs_for += runs_for
            self.away_runs_against += runs_against
        self.recent_results.append((won, runs_for - runs_against))


@dataclass
class PitcherStats:
    era: float = 4.25
    whip: float = 1.30
    k9: float = 8.5
    starts: int = 0
    recent3_era: float = 4.25


def consensus_american_odds(books: list[dict[str, Any]], side: str, line_type: str) -> int | None:
    values: list[int] = []
    for book in books:
        line = book.get(line_type)
        if not line:
            continue
        value = line.get(side)
        if value is None:
            continue
        values.append(int(value))
    if not values:
        return None
    values.sort()
    return values[len(values) // 2]


def load_historical_games(start_season: int, end_season: int) -> list[dict[str, Any]]:
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    games: list[dict[str, Any]] = []
    for day, entries in raw.items():
        season = int(day[:4])
        if season < start_season or season > end_season:
            continue
        for entry in entries:
            game_view = entry.get("gameView", {})
            odds = entry.get("odds", {})
            moneyline_books = odds.get("moneyline") or []
            open_home = consensus_american_odds(moneyline_books, "homeOdds", "openingLine")
            open_away = consensus_american_odds(moneyline_books, "awayOdds", "openingLine")
            close_home = consensus_american_odds(moneyline_books, "homeOdds", "currentLine")
            close_away = consensus_american_odds(moneyline_books, "awayOdds", "currentLine")
            if None in (open_home, open_away, close_home, close_away):
                continue
            if 0 in (open_home, open_away, close_home, close_away):
                continue

            away_score = game_view.get("awayTeamScore")
            home_score = game_view.get("homeTeamScore")
            if away_score is None or home_score is None:
                continue

            games.append(
                {
                    "date": day,
                    "season": season,
                    "start": datetime.fromisoformat(game_view["startDate"].replace("Z", "+00:00")),
                    "away_team": normalize_team_name(game_view["awayTeam"]["fullName"]),
                    "home_team": normalize_team_name(game_view["homeTeam"]["fullName"]),
                    "away_team_display": game_view["awayTeam"]["fullName"],
                    "home_team_display": game_view["homeTeam"]["fullName"],
                    "away_score": int(away_score),
                    "home_score": int(home_score),
                    "open_home": open_home,
                    "open_away": open_away,
                    "close_home": close_home,
                    "close_away": close_away,
                }
            )
    games.sort(key=lambda item: item["start"])
    return games


def load_schedule_cache(season: int) -> dict[tuple[str, str, str], dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"schedule_probables_{season}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = fetch_json(
            f"{STATS_API}/schedule?sportId=1&startDate={season}-03-01&endDate={season}-11-30&hydrate=probablePitcher,team"
        )
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    schedule_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            away_team = game["teams"]["away"]["team"]
            home_team = game["teams"]["home"]["team"]
            if "name" not in away_team or "name" not in home_team:
                continue
            away = normalize_team_name(away_team["name"])
            home = normalize_team_name(home_team["name"])
            key = (day["date"], away, home)
            schedule_map[key] = {
                "away_team_id": away_team.get("id"),
                "home_team_id": home_team.get("id"),
                "away_pitcher_id": game["teams"]["away"].get("probablePitcher", {}).get("id"),
                "home_pitcher_id": game["teams"]["home"].get("probablePitcher", {}).get("id"),
            }
    return schedule_map


def parse_innings_to_outs(innings: str | None) -> int:
    if not innings:
        return 0
    whole, _, partial = innings.partition(".")
    outs = int(whole) * 3
    if partial == "1":
        outs += 1
    elif partial == "2":
        outs += 2
    return outs


@lru_cache(maxsize=None)
def load_pitcher_gamelog(pitcher_id: int, season: int) -> list[dict[str, Any]]:
    folder = CACHE_DIR / "pitcher_gamelogs"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{season}_{pitcher_id}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, list):
            return cached
        data = cached
    else:
        data = fetch_json(
            f"{STATS_API}/people/{pitcher_id}/stats?stats=gameLog&group=pitching&season={season}"
        )

    stats_blocks = data.get("stats") or []
    splits = stats_blocks[0].get("splits", []) if stats_blocks else []
    parsed: list[dict[str, Any]] = []
    def as_float(value: Any, fallback: float = 0.0) -> float:
        if value in (None, "", "-.--", ".---"):
            return fallback
        return float(value)
    for split in splits:
        stat = split.get("stat", {})
        if int(stat.get("gamesStarted", 0) or 0) <= 0:
            continue
        parsed.append(
            {
                "date": split["date"],
                "era": as_float(stat.get("era"), 0.0),
                "whip": as_float(stat.get("whip"), 0.0),
                "k9": as_float(stat.get("strikeoutsPer9Inn"), 0.0),
                "outs": int(stat.get("outs") or parse_innings_to_outs(stat.get("inningsPitched"))),
                "earned_runs": int(stat.get("earnedRuns") or 0),
                "hits": int(stat.get("hits") or 0),
                "walks": int(stat.get("baseOnBalls") or 0),
                "strikeouts": int(stat.get("strikeOuts") or 0),
            }
        )
    cache_path.write_text(json.dumps(parsed), encoding="utf-8")
    return parsed


@lru_cache(maxsize=None)
def load_pitcher_previous_season(pitcher_id: int, season: int) -> PitcherStats:
    folder = CACHE_DIR / "pitcher_season"
    folder.mkdir(parents=True, exist_ok=True)
    cache_path = folder / f"{season}_{pitcher_id}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if "stats" in payload:
            stats_blocks = payload.get("stats") or []
            splits = stats_blocks[0].get("splits", []) if stats_blocks else []
            stat = splits[0]["stat"] if splits else {}
            payload = {
                "era": float(stat.get("era") or 4.25),
                "whip": float(stat.get("whip") or 1.30),
                "k9": float(stat.get("strikeoutsPer9Inn") or 8.5),
                "starts": int(stat.get("gamesStarted") or 0),
            }
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        data = fetch_json(
            f"{STATS_API}/people/{pitcher_id}/stats?stats=season&group=pitching&season={season}"
        )
        stats_blocks = data.get("stats") or []
        splits = stats_blocks[0].get("splits", []) if stats_blocks else []
        stat = splits[0]["stat"] if splits else {}
        payload = {
            "era": float(stat.get("era") or 4.25),
            "whip": float(stat.get("whip") or 1.30),
            "k9": float(stat.get("strikeoutsPer9Inn") or 8.5),
            "starts": int(stat.get("gamesStarted") or 0),
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return PitcherStats(
        era=float(payload["era"]),
        whip=float(payload["whip"]),
        k9=float(payload["k9"]),
        starts=int(payload["starts"]),
        recent3_era=float(payload["era"]),
    )


@lru_cache(maxsize=None)
def load_pitcher_precalc(pitcher_id: int, season: int) -> dict[str, Any]:
    starts = load_pitcher_gamelog(pitcher_id, season)
    dates = [item["date"] for item in starts]
    cum_outs: list[int] = []
    cum_earned_runs: list[int] = []
    cum_hits_walks: list[int] = []
    cum_strikeouts: list[int] = []
    recent3_eras: list[float] = []

    total_outs = 0
    total_earned_runs = 0
    total_hits_walks = 0
    total_strikeouts = 0

    for idx, item in enumerate(starts):
        total_outs += item["outs"]
        total_earned_runs += item["earned_runs"]
        total_hits_walks += item["hits"] + item["walks"]
        total_strikeouts += item["strikeouts"]
        cum_outs.append(total_outs)
        cum_earned_runs.append(total_earned_runs)
        cum_hits_walks.append(total_hits_walks)
        cum_strikeouts.append(total_strikeouts)

        recent_three = starts[max(0, idx - 2): idx + 1]
        recent_outs = sum(start["outs"] for start in recent_three)
        recent_innings = recent_outs / 3 if recent_outs else 0.0
        recent_earned = sum(start["earned_runs"] for start in recent_three)
        recent3_eras.append((recent_earned * 9 / recent_innings) if recent_innings else 4.25)

    return {
        "dates": dates,
        "cum_outs": cum_outs,
        "cum_earned_runs": cum_earned_runs,
        "cum_hits_walks": cum_hits_walks,
        "cum_strikeouts": cum_strikeouts,
        "recent3_eras": recent3_eras,
    }


def get_pitcher_pre_stats(pitcher_id: int | None, season: int, game_date: str) -> PitcherStats:
    if not pitcher_id:
        return PitcherStats()

    precalc = load_pitcher_precalc(pitcher_id, season)
    dates = precalc["dates"]
    cutoff = bisect.bisect_left(dates, game_date)
    if cutoff <= 0:
        return load_pitcher_previous_season(pitcher_id, season - 1)

    outs = precalc["cum_outs"][cutoff - 1]
    innings = outs / 3 if outs else 0.0
    earned_runs = precalc["cum_earned_runs"][cutoff - 1]
    hits_walks = precalc["cum_hits_walks"][cutoff - 1]
    strikeouts = precalc["cum_strikeouts"][cutoff - 1]

    current = PitcherStats(
        era=(earned_runs * 9 / innings) if innings else 4.25,
        whip=(hits_walks / innings) if innings else 1.30,
        k9=(strikeouts * 9 / innings) if innings else 8.5,
        starts=cutoff,
        recent3_era=precalc["recent3_eras"][cutoff - 1],
    )

    if cutoff < 4:
        previous = load_pitcher_previous_season(pitcher_id, season - 1)
        weight = 0.35 + 0.15 * min(cutoff, 3)
        prev_weight = 1.0 - weight
        return PitcherStats(
            era=weight * current.era + prev_weight * previous.era,
            whip=weight * current.whip + prev_weight * previous.whip,
            k9=weight * current.k9 + prev_weight * previous.k9,
            starts=cutoff,
            recent3_era=current.recent3_era,
        )

    return current


def starter_score(stats: PitcherStats) -> float:
    return (
        ((5.0 - stats.era) / 2.0)
        + (1.35 - stats.whip)
        + ((stats.k9 - 8.0) / 4.0)
        + ((5.0 - stats.recent3_era) / 2.0)
    ) / 4.0


def model_probability(
    away_state: TeamState,
    home_state: TeamState,
    away_starter: PitcherStats,
    home_starter: PitcherStats,
    open_away_odds: int,
    open_home_odds: int,
) -> float:
    away_market_prob = american_to_probability(open_away_odds)
    home_market_prob = american_to_probability(open_home_odds)
    market_prob = away_market_prob / (away_market_prob + home_market_prob)
    market_logit = probability_to_logit(market_prob)

    recent_win_edge = away_state.recent_win_pct() - home_state.recent_win_pct()
    recent_rd_edge = max(-3.0, min(3.0, away_state.recent_run_diff_pg() - home_state.recent_run_diff_pg()))
    season_win_edge = away_state.season_win_pct() - home_state.season_win_pct()
    season_rd_edge = max(-3.5, min(3.5, away_state.season_run_diff_pg() - home_state.season_run_diff_pg()))
    starter_edge = max(-2.0, min(2.0, starter_score(away_starter) - starter_score(home_starter)))

    adjusted_logit = (
        market_logit
        + 0.32 * recent_win_edge
        + 0.08 * recent_rd_edge
        + 0.24 * season_win_edge
        + 0.06 * season_rd_edge
        + 0.72 * starter_edge
        - 0.08
    )
    return logit_to_probability(adjusted_logit)


def max_drawdown(curve: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def main() -> None:
    parser = argparse.ArgumentParser(description="Starter-aware MLB moneyline backtest.")
    parser.add_argument("--start-season", type=int, default=2025)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--min-edge", type=float, default=0.04)
    parser.add_argument("--min-games", type=int, default=8)
    parser.add_argument("--odds-source", choices=("open", "current"), default="open")
    args = parser.parse_args()
    price_prefix = "close" if args.odds_source == "current" else "open"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    games = load_historical_games(args.start_season, args.end_season)
    schedule_caches = {
        season: load_schedule_cache(season)
        for season in range(args.start_season, args.end_season + 1)
    }

    team_states: dict[str, TeamState] = defaultdict(TeamState)
    bets: list[dict[str, Any]] = []
    bankroll = 0.0
    curve = [0.0]

    for game in games:
        season = game["season"]
        away_state = team_states[game["away_team"]]
        home_state = team_states[game["home_team"]]
        if away_state.season != season:
            away_state.reset(season)
        if home_state.season != season:
            home_state.reset(season)

        if away_state.games_seen() >= args.min_games and home_state.games_seen() >= args.min_games:
            starter_info = schedule_caches[season].get((game["date"], game["away_team"], game["home_team"]), {})
            away_starter = get_pitcher_pre_stats(starter_info.get("away_pitcher_id"), season, game["date"])
            home_starter = get_pitcher_pre_stats(starter_info.get("home_pitcher_id"), season, game["date"])

            away_prob = model_probability(
                away_state,
                home_state,
                away_starter,
                home_starter,
                game[f"{price_prefix}_away"],
                game[f"{price_prefix}_home"],
            )
            home_prob = 1.0 - away_prob
            away_price_prob = american_to_probability(game[f"{price_prefix}_away"])
            home_price_prob = american_to_probability(game[f"{price_prefix}_home"])
            away_close_prob = american_to_probability(game["close_away"])
            home_close_prob = american_to_probability(game["close_home"])
            away_edge = away_prob - away_price_prob
            home_edge = home_prob - home_price_prob

            if away_edge >= home_edge:
                side = "away"
                selection_team = game["away_team_display"]
                selection_edge = away_edge
                selection_prob = away_prob
                selection_odds = game[f"{price_prefix}_away"]
                clv = away_close_prob - away_price_prob
                won = game["away_score"] > game["home_score"]
            else:
                side = "home"
                selection_team = game["home_team_display"]
                selection_edge = home_edge
                selection_prob = home_prob
                selection_odds = game[f"{price_prefix}_home"]
                clv = home_close_prob - home_price_prob
                won = game["home_score"] > game["away_score"]

            if selection_edge >= args.min_edge:
                profit = settle_american_bet(selection_odds, won)
                bankroll += profit
                curve.append(bankroll)
                bets.append(
                    {
                        "date": game["date"],
                        "matchup": f"{game['away_team_display']} @ {game['home_team_display']}",
                        "selection_side": side,
                        "selection_team": selection_team,
                        "opening_odds": selection_odds,
                        "model_probability": selection_prob,
                        "edge": selection_edge,
                        "clv": clv,
                        "won": won,
                        "profit": profit,
                    }
                )

        away_state.record(game["away_score"], game["home_score"])
        home_state.record(game["home_score"], game["away_score"])

    summary = {
        "start_season": args.start_season,
        "end_season": args.end_season,
        "min_edge": args.min_edge,
        "min_games": args.min_games,
        "odds_source": args.odds_source,
        "bets": len(bets),
        "profit_units": sum(item["profit"] for item in bets),
        "roi": (sum(item["profit"] for item in bets) / len(bets)) if bets else 0.0,
        "win_rate": mean(1.0 if item["won"] else 0.0 for item in bets) if bets else 0.0,
        "average_edge": mean(item["edge"] for item in bets) if bets else 0.0,
        "average_clv": mean(item["clv"] for item in bets) if bets else 0.0,
        "max_drawdown_units": max_drawdown(curve),
    }

    stem = f"starter_moneyline_backtest_{args.start_season}_{args.end_season}"
    (OUTPUT_DIR / f"{stem}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUTPUT_DIR / f"{stem}_bets.json").write_text(json.dumps(bets, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
