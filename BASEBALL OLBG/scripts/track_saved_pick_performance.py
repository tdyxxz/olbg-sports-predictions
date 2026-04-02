from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = BASE_DIR / "data" / "cache" / "settlement"
STATS_API = "https://statsapi.mlb.com/api/v1"
SESSION = requests.Session()


def normalize_team_name(name: str) -> str:
    return (
        name.lower()
        .replace("st. ", "st ")
        .replace("d-backs", "diamondbacks")
        .strip()
    )


def settle_american_bet(odds: int, won: bool) -> float:
    if not won:
        return -1.0
    if odds > 0:
        return odds / 100.0
    return 100.0 / (-odds)


def fetch_json(url: str) -> dict[str, Any]:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def load_final_games(target_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{target_date}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = fetch_json(f"{STATS_API}/schedule?sportId=1&date={target_date}")
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    games: dict[tuple[str, str], dict[str, Any]] = {}
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("detailedState") != "Final":
                continue
            away = game["teams"]["away"]
            home = game["teams"]["home"]
            away_name = away["team"]["name"]
            home_name = home["team"]["name"]
            games[(normalize_team_name(away_name), normalize_team_name(home_name))] = {
                "away_team": away_name,
                "home_team": home_name,
                "away_score": int(away.get("score") or 0),
                "home_score": int(home.get("score") or 0),
                "winner": away_name if int(away.get("score") or 0) > int(home.get("score") or 0) else home_name,
            }
    return games


def infer_strategy(path: Path, item: dict[str, Any]) -> str:
    if "strategy" in item:
        return str(item["strategy"])
    match = re.match(r"mlb_predictions_\d{8}(?:_(.+))?\.json$", path.name)
    if not match:
        return "unknown"
    suffix = match.group(1)
    return suffix or "baseline"


def load_pick_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.glob("mlb_predictions_*.json")):
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            continue
        for item in items:
            matchup = str(item.get("matchup") or "")
            if " @ " not in matchup:
                continue
            away_team, home_team = matchup.split(" @ ", 1)
            rows.append(
                {
                    "source_file": path.name,
                    "date": str(item["date"]),
                    "strategy": infer_strategy(path, item),
                    "matchup": matchup,
                    "away_team": away_team,
                    "home_team": home_team,
                    "selection": str(item["selection"]),
                    "odds": int(item["odds"]),
                }
            )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bets = len(rows)
    profit = sum(row["profit"] for row in rows)
    wins = sum(1 for row in rows if row["won"])
    return {
        "bets": bets,
        "wins": wins,
        "losses": bets - wins,
        "profit": round(profit, 4),
        "roi": round((profit / bets) if bets else 0.0, 4),
        "win_rate": round((wins / bets) if bets else 0.0, 4),
    }


def main() -> None:
    rows = load_pick_rows()
    settled: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    by_date: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for row in rows:
        date = row["date"]
        if date not in by_date:
            by_date[date] = load_final_games(date)
        games = by_date[date]
        key = (normalize_team_name(row["away_team"]), normalize_team_name(row["home_team"]))
        result = games.get(key)
        if not result:
            unresolved.append(row)
            continue

        won = row["selection"] == result["winner"]
        settled.append(
            {
                **row,
                "winner": result["winner"],
                "away_score": result["away_score"],
                "home_score": result["home_score"],
                "won": won,
                "profit": round(settle_american_bet(row["odds"], won), 4),
            }
        )

    strategies = sorted({row["strategy"] for row in settled})
    summary_by_strategy = {
        strategy: summarize([row for row in settled if row["strategy"] == strategy])
        for strategy in strategies
    }
    overall = summarize(settled)

    payload = {
        "overall": overall,
        "by_strategy": summary_by_strategy,
        "settled_picks": settled,
        "unresolved_picks": unresolved,
    }

    json_path = OUTPUT_DIR / "saved_pick_performance.json"
    md_path = OUTPUT_DIR / "saved_pick_performance.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Saved Pick Performance",
        "",
        "## Overall",
        "",
        f"- Bets: {overall['bets']}",
        f"- Wins: {overall['wins']}",
        f"- Losses: {overall['losses']}",
        f"- Profit: {overall['profit']:.4f} units",
        f"- ROI: {overall['roi']:.4f}",
        f"- Win Rate: {overall['win_rate']:.4f}",
        "",
        "## By Strategy",
        "",
    ]
    for strategy, summary in summary_by_strategy.items():
        lines.extend(
            [
                f"### {strategy}",
                "",
                f"- Bets: {summary['bets']}",
                f"- Wins: {summary['wins']}",
                f"- Losses: {summary['losses']}",
                f"- Profit: {summary['profit']:.4f} units",
                f"- ROI: {summary['roi']:.4f}",
                f"- Win Rate: {summary['win_rate']:.4f}",
                "",
            ]
        )
    if unresolved:
        lines.extend(
            [
                "## Unresolved",
                "",
                f"- Picks without a final result yet: {len(unresolved)}",
                "",
            ]
        )

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(json.dumps(payload["overall"], indent=2))


if __name__ == "__main__":
    main()
