from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
import time
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CONFIG_DIR = BASE_DIR / "config"
CACHE_DIR = BASE_DIR / "data" / "cache"
OLBG_BOARD_PATH = OUTPUT_DIR / "olbg_baseball_board.json"

STATS_API = "https://statsapi.mlb.com/api/v1"
VEGAS_INSIDER_MLB_ODDS = "https://www.vegasinsider.com/mlb/odds/las-vegas/"
SESSION = requests.Session()

TEAM_ALIASES = {
    "angels": "angels",
    "astros": "astros",
    "athletics": "athletics",
    "a's": "athletics",
    "braves": "braves",
    "blue jays": "blue jays",
    "jays": "blue jays",
    "brewers": "brewers",
    "cardinals": "cardinals",
    "cubs": "cubs",
    "diamondbacks": "diamondbacks",
    "dbacks": "diamondbacks",
    "d-backs": "diamondbacks",
    "dodgers": "dodgers",
    "giants": "giants",
    "guardians": "guardians",
    "mariners": "mariners",
    "marlins": "marlins",
    "mets": "mets",
    "nationals": "nationals",
    "orioles": "orioles",
    "padres": "padres",
    "phillies": "phillies",
    "pirates": "pirates",
    "rangers": "rangers",
    "rays": "rays",
    "reds": "reds",
    "red sox": "red sox",
    "rockies": "rockies",
    "royals": "royals",
    "tigers": "tigers",
    "twins": "twins",
    "white sox": "white sox",
    "yankees": "yankees",
}


@dataclass
class TeamSnapshot:
    team_id: int
    name: str
    norm_name: str
    current_win_pct: float
    current_run_diff_pg: float
    previous_win_pct: float
    previous_run_diff_pg: float
    recent_win_pct: float
    recent_run_diff_pg: float


@dataclass
class PitcherSnapshot:
    pitcher_id: int | None
    name: str | None
    era: float
    whip: float
    k9: float


def fetch_json(url: str) -> dict[str, Any]:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def cache_is_fresh(path: Path, max_age_minutes: int) -> bool:
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_age_minutes * 60


def normalize_team_name(raw_name: str) -> str:
    raw = raw_name.lower().strip()
    raw = raw.replace("st. ", "st ")
    raw = raw.replace("d-backs", "diamondbacks")
    if raw in TEAM_ALIASES:
        return TEAM_ALIASES[raw]

    parts = raw.split()
    if raw.endswith("red sox") or raw.endswith("white sox") or raw.endswith("blue jays"):
        key = " ".join(parts[-2:])
    else:
        key = parts[-1]
    return TEAM_ALIASES.get(key, key)


def load_olbg_matchup_keys() -> set[frozenset[str]]:
    if not OLBG_BOARD_PATH.exists():
        return set()
    payload = json.loads(OLBG_BOARD_PATH.read_text(encoding="utf-8"))
    keys: set[frozenset[str]] = set()
    for fixture in payload.get("fixtures", []):
        matchup_key = fixture.get("matchup_key")
        if isinstance(matchup_key, list) and len(matchup_key) == 2:
            keys.add(frozenset(str(item) for item in matchup_key))
    return keys


def parse_american_odds(raw_value: Any) -> int | None:
    if raw_value is None or (isinstance(raw_value, float) and math.isnan(raw_value)):
        return None
    raw = str(raw_value).strip().lower()
    if not raw or raw == "nan":
        return None
    raw = raw.replace("even", "+100").replace(" +", "").replace(" -", "-")
    raw = raw.split()[0]
    try:
        return int(raw)
    except ValueError:
        return None


def implied_probability(american_odds: int) -> float:
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return (-american_odds) / ((-american_odds) + 100)


def logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def load_moneylines(target_date: str, cache_minutes: int) -> dict[frozenset[str], dict[str, int]]:
    cache_dir = CACHE_DIR / "moneylines"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{target_date}.json"
    if cache_is_fresh(cache_path, cache_minutes):
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return {
            frozenset(entry["teams"]): entry["odds"]
            for entry in payload
        }

    import pandas as pd

    table = pd.read_html(VEGAS_INSIDER_MLB_ODDS)[0]
    moneylines: dict[frozenset[str], dict[str, int]] = {}
    known_teams = set(TEAM_ALIASES.values())

    idx = 0
    while idx < len(table) - 1:
        first = table.iloc[idx]
        second = table.iloc[idx + 1]
        idx += 1

        first_label = first.get("Time")
        second_label = second.get("Time")
        if not isinstance(first_label, str) or not isinstance(second_label, str):
            continue
        if first_label == "Matchup" or second_label == "Matchup":
            continue

        team_one = normalize_team_name(first_label.split(maxsplit=1)[-1])
        team_two = normalize_team_name(second_label.split(maxsplit=1)[-1])
        odds_one = parse_american_odds(first.get("Consensus"))
        odds_two = parse_american_odds(second.get("Consensus"))

        if team_one not in known_teams or team_two not in known_teams:
            continue
        if odds_one is None or odds_two is None:
            continue

        moneylines[frozenset((team_one, team_two))] = {
            team_one: odds_one,
            team_two: odds_two,
        }
        idx += 1

    serializable = [
        {
            "teams": sorted(list(key)),
            "odds": value,
        }
        for key, value in moneylines.items()
    ]
    cache_path.write_text(json.dumps(serializable), encoding="utf-8")
    return moneylines


def load_daily_schedule(target_date: str, cache_minutes: int) -> dict[str, Any]:
    schedule_cache_dir = CACHE_DIR / "daily_schedule"
    schedule_cache_dir.mkdir(parents=True, exist_ok=True)
    schedule_cache_path = schedule_cache_dir / f"{target_date}.json"
    if cache_is_fresh(schedule_cache_path, cache_minutes):
        return json.loads(schedule_cache_path.read_text(encoding="utf-8"))

    schedule = fetch_json(
        f"{STATS_API}/schedule?sportId=1&date={target_date}&hydrate=probablePitcher,team"
    )
    schedule_cache_path.write_text(json.dumps(schedule), encoding="utf-8")
    return schedule


def load_team_records(season: int, cache_key: str | None = None) -> dict[int, dict[str, float]]:
    cache_dir = CACHE_DIR / "team_records"
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = cache_key or f"season_{season}"
    cache_path = cache_dir / f"{suffix}_{season}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return {int(team_id): values for team_id, values in payload.items()}

    data = fetch_json(
        f"{STATS_API}/standings?leagueId=103,104&season={season}&standingsTypes=regularSeason"
    )
    records: dict[int, dict[str, float]] = {}
    for block in data.get("records", []):
        for team_record in block.get("teamRecords", []):
            games_played = max(1, team_record["wins"] + team_record["losses"])
            records[team_record["team"]["id"]] = {
                "win_pct": team_record["wins"] / games_played,
                "run_diff_pg": team_record.get("runDifferential", 0) / games_played,
            }
    cache_path.write_text(json.dumps(records), encoding="utf-8")
    return records


@lru_cache(maxsize=None)
def load_recent_team_form(team_id: int, target_date: str) -> dict[str, float]:
    cache_dir = CACHE_DIR / "recent_team_form"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{target_date}_{team_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    season_start = f"{target_date[:4]}-03-20"
    data = fetch_json(
        f"{STATS_API}/schedule?sportId=1&teamId={team_id}&startDate={season_start}&endDate={target_date}"
    )
    recent_games: list[tuple[bool, int]] = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            if game["status"]["detailedState"] != "Final":
                continue

            away = game["teams"]["away"]
            home = game["teams"]["home"]
            is_home = home["team"]["id"] == team_id
            team_side = home if is_home else away
            opp_side = away if is_home else home
            recent_games.append((team_side["score"] > opp_side["score"], team_side["score"] - opp_side["score"]))

    recent_games = recent_games[-5:]
    if not recent_games:
        result = {"win_pct": 0.5, "run_diff_pg": 0.0}
        cache_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    wins = sum(1 for did_win, _ in recent_games if did_win)
    run_diff = sum(diff for _, diff in recent_games)
    result = {"win_pct": wins / len(recent_games), "run_diff_pg": run_diff / len(recent_games)}
    cache_path.write_text(json.dumps(result), encoding="utf-8")
    return result


@lru_cache(maxsize=None)
def load_pitcher_snapshot(pitcher_id: int | None, season: int, cache_key: str = "default") -> PitcherSnapshot:
    default = PitcherSnapshot(
        pitcher_id=pitcher_id,
        name=None,
        era=4.25,
        whip=1.30,
        k9=8.5,
    )
    if pitcher_id is None:
        return default

    cache_dir = CACHE_DIR / "pitcher_snapshot"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}_{season}_{pitcher_id}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return PitcherSnapshot(
            pitcher_id=payload.get("pitcher_id"),
            name=payload.get("name"),
            era=float(payload.get("era", 4.25)),
            whip=float(payload.get("whip", 1.30)),
            k9=float(payload.get("k9", 8.5)),
        )

    def get_pitching_stats(stat_season: int) -> tuple[str | None, dict[str, Any] | None]:
        data = fetch_json(
            f"{STATS_API}/people/{pitcher_id}/stats?stats=season&group=pitching&season={stat_season}"
        )
        stats_blocks = data.get("stats") or []
        if not stats_blocks:
            return None, None
        splits = stats_blocks[0].get("splits", [])
        if not splits:
            return None, None
        split = splits[0]
        return split.get("player", {}).get("fullName"), split.get("stat", {})

    current_name, current_stats = get_pitching_stats(season)
    previous_name, previous_stats = get_pitching_stats(season - 1)

    if not current_stats and not previous_stats:
        default.name = current_name or previous_name
        return default

    def metric(stats: dict[str, Any] | None, field: str, fallback: float) -> float:
        if not stats:
            return fallback
        value = stats.get(field)
        if value in (None, ""):
            return fallback
        return float(value)

    if current_stats and previous_stats:
        era = 0.35 * metric(current_stats, "era", 4.25) + 0.65 * metric(previous_stats, "era", 4.25)
        whip = 0.35 * metric(current_stats, "whip", 1.30) + 0.65 * metric(previous_stats, "whip", 1.30)
        k9 = 0.35 * metric(current_stats, "strikeoutsPer9Inn", 8.5) + 0.65 * metric(previous_stats, "strikeoutsPer9Inn", 8.5)
    else:
        source = current_stats or previous_stats
        era = metric(source, "era", 4.25)
        whip = metric(source, "whip", 1.30)
        k9 = metric(source, "strikeoutsPer9Inn", 8.5)

    snapshot = PitcherSnapshot(
        pitcher_id=pitcher_id,
        name=current_name or previous_name,
        era=era,
        whip=whip,
        k9=k9,
    )
    cache_path.write_text(
        json.dumps(
            {
                "pitcher_id": snapshot.pitcher_id,
                "name": snapshot.name,
                "era": snapshot.era,
                "whip": snapshot.whip,
                "k9": snapshot.k9,
            }
        ),
        encoding="utf-8",
    )
    return snapshot


def build_team_snapshot(
    team_id: int,
    team_name: str,
    season: int,
    current_records: dict[int, dict[str, float]],
    previous_records: dict[int, dict[str, float]],
    target_date: str,
) -> TeamSnapshot:
    current = current_records[team_id]
    previous = previous_records[team_id]
    recent = load_recent_team_form(team_id, target_date)
    return TeamSnapshot(
        team_id=team_id,
        name=team_name,
        norm_name=normalize_team_name(team_name),
        current_win_pct=current["win_pct"],
        current_run_diff_pg=current["run_diff_pg"],
        previous_win_pct=previous["win_pct"],
        previous_run_diff_pg=previous["run_diff_pg"],
        recent_win_pct=recent["win_pct"],
        recent_run_diff_pg=recent["run_diff_pg"],
    )


def team_rating(team: TeamSnapshot, pitcher: PitcherSnapshot) -> float:
    pitcher_component = (
        ((5.0 - pitcher.era) / 2.0)
        + (1.40 - pitcher.whip)
        + ((pitcher.k9 - 8.0) / 4.0)
    ) / 3.0
    return (
        0.22 * team.current_win_pct
        + 0.18 * team.previous_win_pct
        + 0.18 * team.recent_win_pct
        + 0.14 * max(-3.0, min(3.0, team.current_run_diff_pg)) / 3.0
        + 0.10 * max(-3.0, min(3.0, team.previous_run_diff_pg)) / 3.0
        + 0.18 * pitcher_component
    )


def starter_score(pitcher: PitcherSnapshot) -> float:
    return (
        ((5.0 - pitcher.era) / 2.0)
        + (1.35 - pitcher.whip)
        + ((pitcher.k9 - 8.0) / 4.0)
    ) / 3.0


def confidence_from_edge(edge: float) -> str:
    if edge >= 0.10:
        return "HIGH"
    if edge >= 0.06:
        return "MEDIUM"
    return "LOW"


def reason_summary(team: TeamSnapshot, pitcher: PitcherSnapshot) -> list[str]:
    reasons: list[str] = []
    if team.recent_win_pct >= 0.60:
        reasons.append("better recent form")
    if team.current_run_diff_pg > 0.5 or team.previous_run_diff_pg > 0.5:
        reasons.append("stronger run-differential profile")
    if pitcher.era <= 3.75 or pitcher.whip <= 1.20:
        reasons.append("clear starting-pitcher edge")
    if not reasons:
        reasons.append("the more stable overall game shape")
    return reasons


def load_strategy_config(config_path: str | None) -> dict[str, Any] | None:
    if not config_path:
        return None
    path = Path(config_path)
    if not path.is_absolute():
        path = (BASE_DIR / config_path).resolve()
    return json.loads(path.read_text(encoding="utf-8"))


def odds_band_match(odds: int, band_name: str) -> bool:
    if band_name == "all":
        return True
    if band_name == "heavy_favorites":
        return odds <= -300
    if band_name == "favorites_200_plus":
        return odds <= -200
    if band_name == "mid_favorites":
        return -199 <= odds <= -110
    if band_name == "short_underdogs":
        return 100 < odds <= 150
    if band_name == "heavy_or_short_dog":
        return odds <= -300 or (100 < odds <= 150)
    if band_name == "favorites_200_plus_or_short_dog":
        return odds <= -200 or (100 < odds <= 150)
    return True


def config_probability(
    config: dict[str, Any],
    away_team: TeamSnapshot,
    home_team: TeamSnapshot,
    away_pitcher: PitcherSnapshot,
    home_pitcher: PitcherSnapshot,
    away_odds: int,
    home_odds: int,
) -> float:
    away_market = implied_probability(away_odds)
    home_market = implied_probability(home_odds)
    market_away = away_market / (away_market + home_market)
    weights = config["weights"]
    adjustment = (
        weights["recent_win_edge"] * (away_team.recent_win_pct - home_team.recent_win_pct)
        + weights["recent_rd_edge"] * (away_team.recent_run_diff_pg - home_team.recent_run_diff_pg)
        + weights["season_win_edge"] * (away_team.current_win_pct - home_team.current_win_pct)
        + weights["season_rd_edge"] * (away_team.current_run_diff_pg - home_team.current_run_diff_pg)
        + weights["starter_edge"] * (starter_score(away_pitcher) - starter_score(home_pitcher))
    )
    return logistic(logit(market_away) + adjustment)


def public_reason_text(item: dict[str, Any], index: int) -> str:
    reason_text = ", ".join(item["reasons"])
    selection = item["selection"]
    matchup = item["matchup"]
    variants = [
        f"**{selection}** should win this matchup because the overall shape of the game points their way. "
        f"They bring {reason_text}, and that combination gives them the steadier path over nine innings instead "
        f"of needing one short burst to steal it.",
        f"Backing **{selection}** here comes down to how the contest is likely to unfold. "
        f"The stronger case sits with {reason_text}, and that profile is better built to control the middle innings "
        f"and keep {matchup} from turning into a late scramble.",
        f"**{selection}** is the side to trust because the cleaner route to victory belongs to them. "
        f"They hold {reason_text}, which matters in baseball when small edges stack up gradually and force the other club "
        f"to play from behind.",
    ]
    return variants[index % len(variants)]


def write_outputs(target_date: str, predictions: list[dict[str, Any]], strategy_name: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = target_date.replace("-", "")
    suffix = "" if strategy_name == "baseline" else f"_{strategy_name}"
    json_path = OUTPUT_DIR / f"mlb_predictions_{stamp}{suffix}.json"
    md_path = OUTPUT_DIR / f"mlb_predictions_{stamp}{suffix}.md"

    json_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")

    lines = [f"# MLB Predictions for {target_date}", "", "| Matchup | Pick | Confidence |", "|---|---|---|"]
    for idx, item in enumerate(predictions):
        lines.append(
            f"| {item['matchup']} | {item['selection']} | {item['confidence']} |"
        )
        lines.append("")
        lines.append(public_reason_text(item, idx))
        lines.append("")

    if not predictions:
        lines.append("NO BET")
        lines.append("")
        lines.append("No matchup cleared the current edge threshold.")

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


def write_json_only(target_date: str, predictions: list[dict[str, Any]], strategy_name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = target_date.replace("-", "")
    suffix = "" if strategy_name == "baseline" else f"_{strategy_name}"
    json_path = OUTPUT_DIR / f"mlb_predictions_{stamp}{suffix}.json"
    json_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    return json_path


def warm_live_inputs(games: list[dict[str, Any]], season: int, target_date: str, workers: int) -> None:
    team_ids = {
        side["team"]["id"]
        for game in games
        for side in (game["teams"]["away"], game["teams"]["home"])
    }
    pitcher_ids = {
        side.get("probablePitcher", {}).get("id")
        for game in games
        for side in (game["teams"]["away"], game["teams"]["home"])
        if side.get("probablePitcher", {}).get("id") is not None
    }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        recent_jobs = [executor.submit(load_recent_team_form, team_id, target_date) for team_id in sorted(team_ids)]
        pitcher_jobs = [
            executor.submit(load_pitcher_snapshot, pitcher_id, season, target_date)
            for pitcher_id in sorted(pitcher_ids)
        ]
        for job in recent_jobs + pitcher_jobs:
            job.result()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a no-key MLB prediction card.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.04,
        help="Minimum edge required to keep a selection.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON config path for an experimental weighted selection regime.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip markdown generation and write JSON only for faster internal runs.",
    )
    parser.add_argument(
        "--live-cache-minutes",
        type=int,
        default=10,
        help="Freshness window in minutes for live moneyline and schedule caches.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Worker count for live cache warming on the first run.",
    )
    parser.add_argument(
        "--ignore-olbg-board",
        action="store_true",
        help="Allow non-OLBG fixtures for internal fallback runs.",
    )
    args = parser.parse_args()

    season = int(args.date[:4])
    with ThreadPoolExecutor(max_workers=3) as executor:
        current_records_future = executor.submit(load_team_records, season, args.date)
        previous_records_future = executor.submit(load_team_records, season - 1, f"season_{season - 1}")
        moneylines_future = executor.submit(load_moneylines, args.date, args.live_cache_minutes)
        schedule_future = executor.submit(load_daily_schedule, args.date, args.live_cache_minutes)
        current_records = current_records_future.result()
        previous_records = previous_records_future.result()
        moneylines = moneylines_future.result()
        schedule = schedule_future.result()
    olbg_matchup_keys = load_olbg_matchup_keys()

    config = load_strategy_config(args.config)
    dates = schedule.get("dates", [])
    games = dates[0].get("games", []) if dates else []
    pregame_games = [game for game in games if game["status"]["detailedState"] == "Pre-Game"]
    warm_live_inputs(pregame_games, season, args.date, args.workers)

    predictions: list[dict[str, Any]] = []
    for game in pregame_games:

        away_team = game["teams"]["away"]["team"]
        home_team = game["teams"]["home"]["team"]
        key = frozenset(
            {
                normalize_team_name(away_team["name"]),
                normalize_team_name(home_team["name"]),
            }
        )
        if olbg_matchup_keys and key not in olbg_matchup_keys and not args.ignore_olbg_board:
            continue
        if key not in moneylines:
            continue

        away_snapshot = build_team_snapshot(
            team_id=away_team["id"],
            team_name=away_team["name"],
            season=season,
            current_records=current_records,
            previous_records=previous_records,
            target_date=args.date,
        )
        home_snapshot = build_team_snapshot(
            team_id=home_team["id"],
            team_name=home_team["name"],
            season=season,
            current_records=current_records,
            previous_records=previous_records,
            target_date=args.date,
        )

        away_pitcher = load_pitcher_snapshot(
            game["teams"]["away"].get("probablePitcher", {}).get("id"),
            season,
            cache_key=args.date,
        )
        home_pitcher = load_pitcher_snapshot(
            game["teams"]["home"].get("probablePitcher", {}).get("id"),
            season,
            cache_key=args.date,
        )

        away_rating = team_rating(away_snapshot, away_pitcher)
        home_rating = team_rating(home_snapshot, home_pitcher)

        away_odds = moneylines[key][away_snapshot.norm_name]
        home_odds = moneylines[key][home_snapshot.norm_name]
        if config:
            away_probability = config_probability(
                config,
                away_snapshot,
                home_snapshot,
                away_pitcher,
                home_pitcher,
                away_odds,
                home_odds,
            )
        else:
            home_advantage = 0.035
            away_probability = logistic((away_rating - (home_rating + home_advantage)) * 4.0)
        home_probability = 1.0 - away_probability

        away_edge = away_probability - implied_probability(away_odds)
        home_edge = home_probability - implied_probability(home_odds)

        if away_edge >= home_edge:
            selection = away_snapshot.name
            selection_probability = away_probability
            selection_odds = away_odds
            selection_edge = away_edge
            reasons = reason_summary(away_snapshot, away_pitcher)
        else:
            selection = home_snapshot.name
            selection_probability = home_probability
            selection_odds = home_odds
            selection_edge = home_edge
            reasons = reason_summary(home_snapshot, home_pitcher)

        min_edge = float(config["min_edge"]) if config else args.min_edge
        band_name = str(config["band"]) if config else "all"
        if selection_edge < min_edge:
            continue
        if not odds_band_match(selection_odds, band_name):
            continue

        predictions.append(
            {
                "date": args.date,
                "matchup": f"{away_snapshot.name} @ {home_snapshot.name}",
                "selection": selection,
                "odds": selection_odds,
                "model_probability": selection_probability,
                "edge": selection_edge,
                "confidence": confidence_from_edge(selection_edge),
                "away_pitcher": away_pitcher.name,
                "home_pitcher": home_pitcher.name,
                "reasons": reasons,
                "strategy": config["name"] if config else "baseline",
            }
        )

    predictions.sort(key=lambda item: item["edge"], reverse=True)
    strategy_name = config["name"] if config else "baseline"
    if args.fast:
        json_path = write_json_only(args.date, predictions, strategy_name)
        md_path = None
    else:
        json_path, md_path = write_outputs(args.date, predictions, strategy_name)

    print(f"Generated {len(predictions)} active picks for {args.date}")
    print(f"JSON: {json_path}")
    if md_path is not None:
        print(f"Markdown: {md_path}")
    for item in predictions:
        print(
            f"{item['matchup']}: {item['selection']} "
            f"(edge={item['edge']:.1%}, confidence={item['confidence']})"
        )


if __name__ == "__main__":
    main()
