from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = BASE_DIR / "data" / "cache" / "settlement"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SESSION = requests.Session()


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


def load_final_games(target_date: str) -> dict[str, dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{target_date}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = fetch_json(f"{SCOREBOARD_URL}?dates={target_date.replace('-', '')}")
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    games: dict[str, dict[str, Any]] = {}
    for event in payload.get("events", []):
        status = event.get("status", {}).get("type", {})
        if status.get("state") != "post" or not status.get("completed"):
            continue
        competition = event["competitions"][0]
        competitors = competition.get("competitors", [])
        if len(competitors) != 2:
            continue
        home = next(item for item in competitors if item.get("homeAway") == "home")
        away = next(item for item in competitors if item.get("homeAway") == "away")
        home_score = int((home.get("score") or {}).get("value") or (home.get("score") or {}).get("displayValue") or 0)
        away_score = int((away.get("score") or {}).get("value") or (away.get("score") or {}).get("displayValue") or 0)
        winner = home["team"]["displayName"] if home_score > away_score else away["team"]["displayName"]
        games[event["name"]] = {
            "winner": winner,
            "home_score": home_score,
            "away_score": away_score,
        }
    return games


def infer_strategy(path: Path, item: dict[str, Any]) -> str:
    if "strategy" in item:
        return str(item["strategy"])
    match = re.match(r"nba_predictions_\d{8}(?:_(.+))?\.json$", path.name)
    if not match:
        return "unknown"
    suffix = match.group(1)
    return suffix or "baseline"


def load_pick_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.glob("nba_predictions_*.json")):
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            continue
        for item in items:
            matchup = str(item.get("matchup") or "")
            if " at " not in matchup:
                continue
            rows.append(
                {
                    "source_file": path.name,
                    "date": str(item["date"]),
                    "strategy": infer_strategy(path, item),
                    "matchup": matchup,
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
    by_date: dict[str, dict[str, dict[str, Any]]] = {}

    for row in rows:
        target_date = row["date"]
        if target_date not in by_date:
            by_date[target_date] = load_final_games(target_date)
        result = by_date[target_date].get(row["matchup"])
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
        lines.extend(["## Unresolved", "", f"- Picks without a final result yet: {len(unresolved)}", ""])
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()
