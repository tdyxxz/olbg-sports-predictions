from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = BASE_DIR / "data" / "cache"
CONFIG_DIR = BASE_DIR / "config"
SESSION = requests.Session()
OLBG_BOARD_PATH = OUTPUT_DIR / "olbg_basketball_board.json"

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_TEAM_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"

TEAM_ALIASES = {
    "atl hawks": "hawks",
    "hawks": "hawks",
    "boston celtics": "celtics",
    "bos celtics": "celtics",
    "celtics": "celtics",
    "brooklyn nets": "nets",
    "bkn nets": "nets",
    "nets": "nets",
    "charlotte hornets": "hornets",
    "cha hornets": "hornets",
    "hornets": "hornets",
    "chicago bulls": "bulls",
    "chi bulls": "bulls",
    "bulls": "bulls",
    "cleveland cavaliers": "cavaliers",
    "cle cavaliers": "cavaliers",
    "cavaliers": "cavaliers",
    "dallas mavericks": "mavericks",
    "dal mavericks": "mavericks",
    "mavericks": "mavericks",
    "denver nuggets": "nuggets",
    "den nuggets": "nuggets",
    "nuggets": "nuggets",
    "detroit pistons": "pistons",
    "det pistons": "pistons",
    "pistons": "pistons",
    "golden state warriors": "warriors",
    "gs warriors": "warriors",
    "warriors": "warriors",
    "houston rockets": "rockets",
    "hou rockets": "rockets",
    "rockets": "rockets",
    "indiana pacers": "pacers",
    "ind pacers": "pacers",
    "pacers": "pacers",
    "la clippers": "clippers",
    "clippers": "clippers",
    "los angeles lakers": "lakers",
    "la lakers": "lakers",
    "lakers": "lakers",
    "memphis grizzlies": "grizzlies",
    "mem grizzlies": "grizzlies",
    "grizzlies": "grizzlies",
    "miami heat": "heat",
    "mia heat": "heat",
    "heat": "heat",
    "milwaukee bucks": "bucks",
    "mil bucks": "bucks",
    "bucks": "bucks",
    "minnesota timberwolves": "timberwolves",
    "min timberwolves": "timberwolves",
    "timberwolves": "timberwolves",
    "new orleans pelicans": "pelicans",
    "no pelicans": "pelicans",
    "pelicans": "pelicans",
    "new york knicks": "knicks",
    "ny knicks": "knicks",
    "knicks": "knicks",
    "oklahoma city thunder": "thunder",
    "okc thunder": "thunder",
    "thunder": "thunder",
    "orlando magic": "magic",
    "orl magic": "magic",
    "magic": "magic",
    "philadelphia 76ers": "76ers",
    "phi 76ers": "76ers",
    "76ers": "76ers",
    "phoenix suns": "suns",
    "phx suns": "suns",
    "suns": "suns",
    "portland trail blazers": "trail blazers",
    "por trail blazers": "trail blazers",
    "trail blazers": "trail blazers",
    "sacramento kings": "kings",
    "sac kings": "kings",
    "kings": "kings",
    "san antonio spurs": "spurs",
    "sa spurs": "spurs",
    "spurs": "spurs",
    "toronto raptors": "raptors",
    "tor raptors": "raptors",
    "raptors": "raptors",
    "utah jazz": "jazz",
    "uta jazz": "jazz",
    "jazz": "jazz",
    "washington wizards": "wizards",
    "wsh wizards": "wizards",
    "was wizards": "wizards",
    "wizards": "wizards",
}


@dataclass
class TeamSnapshot:
    team_id: int
    name: str
    abbreviation: str
    overall_win_pct: float
    venue_win_pct: float
    recent_win_pct: float
    recent_point_diff: float
    top_scorer_ppg: float


def normalize_team_name(raw_name: str) -> str:
    cleaned = raw_name.lower().strip()
    return TEAM_ALIASES.get(cleaned, TEAM_ALIASES.get(cleaned.split()[-1], cleaned))


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


def fetch_json(url: str) -> dict[str, Any]:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def cache_is_fresh(path: Path, max_age_minutes: int) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) <= max_age_minutes * 60


def parse_record_summary(summary: str | None) -> float:
    if not summary or "-" not in summary:
        return 0.5
    wins_text, losses_text = summary.split("-", 1)
    wins = int(wins_text)
    losses = int(losses_text)
    games = wins + losses
    return wins / games if games else 0.5


def parse_score_value(raw_score: Any) -> int:
    if isinstance(raw_score, dict):
        value = raw_score.get("value")
        if value is not None:
            return int(value)
        display = raw_score.get("displayValue")
        if display is not None:
            return int(display)
        return 0
    if raw_score in (None, ""):
        return 0
    return int(raw_score)


def american_to_probability(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)


def logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def odds_band_match(odds: int, band_name: str) -> bool:
    if band_name == "all":
        return True
    if band_name == "favorites":
        return odds <= -110
    if band_name == "short_underdogs":
        return 100 < odds <= 160
    if band_name == "mid_range":
        return -160 <= odds <= 160
    return True


def load_daily_scoreboard(target_date: str, cache_minutes: int) -> dict[str, Any]:
    cache_dir = CACHE_DIR / "daily_scoreboard"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{target_date}.json"
    if cache_is_fresh(cache_path, cache_minutes):
        return json.loads(cache_path.read_text(encoding="utf-8"))
    payload = fetch_json(f"{ESPN_SCOREBOARD}?dates={target_date.replace('-', '')}")
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def load_team_schedule(team_id: int, target_date: str, cache_minutes: int) -> dict[str, Any]:
    cache_dir = CACHE_DIR / "team_schedule"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{target_date}_{team_id}.json"
    if cache_is_fresh(cache_path, cache_minutes):
        return json.loads(cache_path.read_text(encoding="utf-8"))
    payload = fetch_json(f"{ESPN_TEAM_SCHEDULE.format(team_id=team_id)}?dates={target_date.replace('-', '')}")
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def load_recent_team_form(team_id: int, target_date: str, cache_minutes: int) -> dict[str, float]:
    schedule = load_team_schedule(team_id, target_date, cache_minutes)
    games: list[tuple[bool, int]] = []
    for event in schedule.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or event.get("status") or {}
        status_type = status.get("type", {})
        if not status_type.get("completed"):
            continue
        competitors = competition.get("competitors", [])
        if len(competitors) != 2:
            continue
        team_side = next((item for item in competitors if int(item["team"]["id"]) == team_id), None)
        opp_side = next((item for item in competitors if int(item["team"]["id"]) != team_id), None)
        if not team_side or not opp_side:
            continue
        team_score = parse_score_value(team_side.get("score"))
        opp_score = parse_score_value(opp_side.get("score"))
        games.append((team_score > opp_score, team_score - opp_score))

    recent = games[-5:]
    if not recent:
        return {"win_pct": 0.5, "point_diff": 0.0}
    wins = sum(1 for won, _ in recent if won)
    point_diff = sum(diff for _, diff in recent)
    return {"win_pct": wins / len(recent), "point_diff": point_diff / len(recent)}


def parse_moneyline(competition: dict[str, Any], home_id: int, away_id: int) -> tuple[int | None, int | None]:
    odds = competition.get("odds") or []
    if not odds:
        return None, None
    moneyline = odds[0].get("moneyline") or {}
    home = moneyline.get("home", {}).get("close", {}).get("odds") or moneyline.get("home", {}).get("open", {}).get("odds")
    away = moneyline.get("away", {}).get("close", {}).get("odds") or moneyline.get("away", {}).get("open", {}).get("odds")
    try:
        return int(home), int(away)
    except (TypeError, ValueError):
        return None, None


def load_strategy_config(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = CONFIG_DIR / candidate
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["path"] = str(candidate)
    return payload


def load_snapshot_from_scoreboard(
    competitor: dict[str, Any],
    target_date: str,
    cache_minutes: int,
) -> TeamSnapshot:
    team = competitor["team"]
    records = {item.get("type"): item.get("summary") for item in competitor.get("records", [])}
    recent = load_recent_team_form(int(team["id"]), target_date, cache_minutes)
    leaders = competitor.get("leaders") or []
    top_scorer_ppg = 0.0
    points_leader = next((item for item in leaders if item.get("name") == "pointsPerGame"), None)
    if points_leader and points_leader.get("leaders"):
        top_scorer_ppg = float(points_leader["leaders"][0].get("value") or 0.0)

    venue_key = "home" if competitor.get("homeAway") == "home" else "road"
    return TeamSnapshot(
        team_id=int(team["id"]),
        name=team["displayName"],
        abbreviation=team["abbreviation"],
        overall_win_pct=parse_record_summary(records.get("total")),
        venue_win_pct=parse_record_summary(records.get(venue_key)),
        recent_win_pct=recent["win_pct"],
        recent_point_diff=recent["point_diff"],
        top_scorer_ppg=top_scorer_ppg,
    )


def confidence_from_edge(edge: float) -> str:
    if edge >= 0.09:
        return "HIGH"
    if edge >= 0.05:
        return "MEDIUM"
    return "LOW"


def reason_parts(team: TeamSnapshot) -> list[str]:
    parts: list[str] = []
    if team.recent_win_pct >= 0.6:
        parts.append(f"won {round(team.recent_win_pct * 5):.0f} of their last 5")
    if team.recent_point_diff >= 4:
        parts.append(f"a strong recent scoring margin of {team.recent_point_diff:.1f} points per game")
    if team.venue_win_pct >= 0.58:
        parts.append("a reliable record in this venue split")
    if team.top_scorer_ppg >= 24:
        parts.append(f"a proven lead scorer averaging {team.top_scorer_ppg:.1f} points")
    if not parts:
        parts.append("the steadier current team profile")
    return parts


def public_reason_text(item: dict[str, Any], index: int) -> str:
    reason_text = ", ".join(item["reason_parts"])
    selection = item["selection"]
    variants = [
        f"**{selection}** should win because they bring {reason_text}, and that gives them the cleaner route over four quarters. This matchup looks more likely to be decided by steadiness than one hot shooting spell.",
        f"Backing **{selection}** here comes down to game shape. They have {reason_text}, which is the better foundation for controlling pace, surviving runs, and closing the night with fewer empty possessions.",
        f"**{selection}** is the team to side with because they hold {reason_text}. In an NBA matchup like this, that usually matters when the game tightens late and every defensive stop starts to carry more weight.",
    ]
    return variants[index % len(variants)]


def write_outputs(target_date: str, predictions: list[dict[str, Any]], strategy_name: str, fast: bool) -> tuple[Path, Path | None]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = target_date.replace("-", "")
    suffix = "" if strategy_name == "baseline" else f"_{strategy_name}"
    json_path = OUTPUT_DIR / f"nba_predictions_{stamp}{suffix}.json"
    json_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    if fast:
        return json_path, None

    md_path = OUTPUT_DIR / f"nba_predictions_{stamp}{suffix}.md"
    lines = [f"# NBA Predictions for {target_date}", "", "| Matchup | Pick | Confidence |", "|---|---|---|"]
    for idx, item in enumerate(predictions):
        lines.append(f"| {item['matchup']} | {item['selection']} | {item['confidence']} |")
        lines.append("")
        lines.append(public_reason_text(item, idx))
        lines.append("")
    if not predictions:
        lines.extend(["NO BET", "", "No matchup cleared the current edge threshold."])
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


def warm_live_inputs(events: list[dict[str, Any]], target_date: str, cache_minutes: int, workers: int) -> None:
    team_ids = set()
    for event in events:
        competition = event["competitions"][0]
        for competitor in competition["competitors"]:
            team_ids.add(int(competitor["team"]["id"]))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(load_recent_team_form, team_id, target_date, cache_minutes) for team_id in sorted(team_ids)]
        for future in futures:
            future.result()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a cache-first NBA prediction card.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--min-edge", type=float, default=0.04, help="Minimum edge required to keep a selection.")
    parser.add_argument("--config", default=None, help="Optional JSON config path for an experimental weighted selection regime.")
    parser.add_argument("--fast", action="store_true", help="Skip markdown generation and write JSON only.")
    parser.add_argument("--cache-minutes", type=int, default=10, help="Freshness window for live cache artifacts.")
    parser.add_argument("--workers", type=int, default=8, help="Worker count for live cache warmup.")
    parser.add_argument("--ignore-olbg-board", action="store_true", help="Allow non-OLBG fixtures for internal fallback runs.")
    args = parser.parse_args()

    with ThreadPoolExecutor(max_workers=1) as executor:
        scoreboard = executor.submit(load_daily_scoreboard, args.date, args.cache_minutes).result()
    olbg_matchup_keys = load_olbg_matchup_keys()
    config = load_strategy_config(args.config)

    events = scoreboard.get("events", [])
    pregame_events = [event for event in events if event.get("status", {}).get("type", {}).get("state") == "pre"]
    warm_live_inputs(pregame_events, args.date, args.cache_minutes, args.workers)

    predictions: list[dict[str, Any]] = []
    for event in pregame_events:
        competition = event["competitions"][0]
        competitors = competition["competitors"]
        home = next(item for item in competitors if item["homeAway"] == "home")
        away = next(item for item in competitors if item["homeAway"] == "away")
        matchup_key = frozenset(
            (
                normalize_team_name(home["team"]["displayName"]),
                normalize_team_name(away["team"]["displayName"]),
            )
        )
        if olbg_matchup_keys and matchup_key not in olbg_matchup_keys and not args.ignore_olbg_board:
            continue

        home_odds, away_odds = parse_moneyline(competition, int(home["team"]["id"]), int(away["team"]["id"]))
        if home_odds is None or away_odds is None:
            continue

        home_snapshot = load_snapshot_from_scoreboard(home, args.date, args.cache_minutes)
        away_snapshot = load_snapshot_from_scoreboard(away, args.date, args.cache_minutes)

        market_home = american_to_probability(home_odds)
        market_away = american_to_probability(away_odds)
        market_home_prob = market_home / (market_home + market_away)
        weights = (config or {}).get("weights", {})
        adjustment = (
            float(weights.get("overall_win_pct_edge", 0.45)) * (home_snapshot.overall_win_pct - away_snapshot.overall_win_pct)
            + float(weights.get("venue_win_pct_edge", 0.30)) * (home_snapshot.venue_win_pct - away_snapshot.venue_win_pct)
            + float(weights.get("recent_win_pct_edge", 0.35)) * (home_snapshot.recent_win_pct - away_snapshot.recent_win_pct)
            + float(weights.get("recent_point_diff_edge", 0.018)) * (home_snapshot.recent_point_diff - away_snapshot.recent_point_diff)
            + float(weights.get("top_scorer_ppg_edge", 0.012)) * (home_snapshot.top_scorer_ppg - away_snapshot.top_scorer_ppg)
        )
        home_probability = logistic(logit(market_home_prob) + adjustment)
        away_probability = 1.0 - home_probability

        home_edge = home_probability - american_to_probability(home_odds)
        away_edge = away_probability - american_to_probability(away_odds)
        if home_edge >= away_edge:
            selection = home_snapshot.name
            selection_odds = home_odds
            selection_probability = home_probability
            selection_edge = home_edge
            reason_snapshot = home_snapshot
        else:
            selection = away_snapshot.name
            selection_odds = away_odds
            selection_probability = away_probability
            selection_edge = away_edge
            reason_snapshot = away_snapshot

        min_edge = float((config or {}).get("min_edge", args.min_edge))
        band = str((config or {}).get("band", "all"))
        if selection_edge < min_edge or not odds_band_match(selection_odds, band):
            continue

        predictions.append(
            {
                "date": args.date,
                "matchup": event["name"],
                "selection": selection,
                "odds": selection_odds,
                "model_probability": selection_probability,
                "edge": selection_edge,
                "confidence": confidence_from_edge(selection_edge),
                "reason_parts": reason_parts(reason_snapshot),
                "strategy": str((config or {}).get("name", "baseline")),
            }
        )

    predictions.sort(key=lambda item: item["edge"], reverse=True)
    strategy_name = str((config or {}).get("name", "baseline"))
    json_path, md_path = write_outputs(args.date, predictions, strategy_name, args.fast)
    print(f"Generated {len(predictions)} active picks for {args.date}")
    print(f"JSON: {json_path}")
    if md_path is not None:
        print(f"Markdown: {md_path}")
    for item in predictions:
        print(f"{item['matchup']}: {item['selection']} (edge={item['edge']:.1%}, confidence={item['confidence']})")


if __name__ == "__main__":
    main()
