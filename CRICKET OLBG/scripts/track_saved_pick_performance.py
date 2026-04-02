from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = BASE_DIR / "data" / "cache" / "settlement"
SESSION = requests.Session()


def settle_decimal_bet(decimal_odds: float, won: bool) -> float:
    return round(decimal_odds - 1.0, 4) if won else -1.0


def fetch_event_html(event_id: str, event_url: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{event_id or 'unknown'}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    response = SESSION.get(event_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    cache_path.write_text(response.text, encoding="utf-8")
    return response.text


def infer_strategy(path: Path, item: dict[str, Any]) -> str:
    if "strategy" in item:
        return str(item["strategy"])
    match = re.match(r"cricket_predictions_\d{8}(?:_(.+))?\.json$", path.name)
    if not match:
        return "unknown"
    suffix = match.group(1)
    return suffix or "baseline"


def normalize_team_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def detect_winner_from_html(html: str, teams: list[str]) -> str | None:
    normalized_teams = sorted({normalize_team_label(team) for team in teams if team})
    text = re.sub(r"\s+", " ", html)
    patterns = [
        r"([A-Za-z0-9 .&'-]+?) won by",
        r"winner[^A-Za-z0-9]{0,12}([A-Za-z0-9 .&'-]+?)<",
        r"result[^A-Za-z0-9]{0,12}([A-Za-z0-9 .&'-]+?) won",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            candidate = normalize_team_label(match.group(1))
            for team in normalized_teams:
                if team in candidate or candidate in team:
                    return team
    return None


def parse_teams_from_event_name(event_name: str) -> list[str]:
    if " vs " in event_name:
        left, right = event_name.split(" vs ", 1)
        return [left, right]
    if " @ " in event_name:
        left, right = event_name.split(" @ ", 1)
        return [left, right]
    return [event_name]


def load_pick_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.glob("cricket_predictions_*.json")):
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            continue
        for item in items:
            rows.append(
                {
                    "source_file": path.name,
                    "date": str(item["date"]),
                    "strategy": infer_strategy(path, item),
                    "event_id": str(item.get("event_id") or ""),
                    "event_url": str(item.get("event_url") or ""),
                    "event_name": str(item["event_name"]),
                    "selection": str(item["selection"]),
                    "market": str(item["market"]),
                    "decimal_odds": float(item["decimal_odds"]),
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

    for row in rows:
        event_url = row["event_url"]
        if not event_url:
            unresolved.append({**row, "reason": "missing_event_url"})
            continue
        html = fetch_event_html(row["event_id"], event_url)
        winner = detect_winner_from_html(html, parse_teams_from_event_name(row["event_name"]))
        if not winner:
            unresolved.append({**row, "reason": "winner_not_detected"})
            continue
        won = normalize_team_label(row["selection"]) == winner
        settled.append(
            {
                **row,
                "winner": winner,
                "won": won,
                "profit": settle_decimal_bet(row["decimal_odds"], won),
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
        lines.extend(["## Unresolved", "", f"- Picks without a confirmed detected winner: {len(unresolved)}", ""])
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()
