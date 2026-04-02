from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
OLBG_BOARD_PATH = OUTPUT_DIR / "olbg_cricket_board.json"
ACCEPTED_MARKETS = {"Win Match", "Draw No Bet"}


def parse_decimal(odds_payload: dict[str, Any]) -> float | None:
    raw = odds_payload.get("decimal")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_percent(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return float(raw.replace("%", "").strip()) / 100.0
    except ValueError:
        return None


def confidence_from_edge(edge: float) -> str:
    if edge >= 0.12:
        return "HIGH"
    if edge >= 0.07:
        return "MEDIUM"
    return "LOW"


def load_board() -> dict[str, Any]:
    if not OLBG_BOARD_PATH.exists():
        raise SystemExit(f"Missing OLBG board file: {OLBG_BOARD_PATH}")
    return json.loads(OLBG_BOARD_PATH.read_text(encoding="utf-8"))


def current_or_future(item: dict[str, Any], target_date: str) -> bool:
    start_datetime = item.get("start_datetime")
    if not start_datetime:
        return True
    try:
        dt = datetime.fromisoformat(str(start_datetime).replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt.date() >= datetime.strptime(target_date, "%Y-%m-%d").date()


def board_probability(item: dict[str, Any], decimal_odds: float) -> float:
    implied = 1.0 / decimal_odds
    consensus = parse_percent(str(item.get("consensus_percent") or "")) or 0.5
    win_tips = int(item.get("win_tips") or 0)
    total_tips = int(item.get("total_tips") or 0)
    comment_count = int(item.get("comment_count") or 0)
    expert_bonus = 0.015 if win_tips >= 5 else 0.0
    depth_bonus = min(0.03, total_tips * 0.003)
    discussion_bonus = min(0.015, comment_count * 0.003)
    consensus_component = 0.5 + 0.55 * (consensus - 0.5)
    blended = 0.55 * implied + 0.45 * consensus_component + expert_bonus + depth_bonus + discussion_bonus
    return min(max(blended, 0.02), 0.98)


def public_reason(item: dict[str, Any], index: int) -> str:
    selection = item["selection"]
    market = item["market"]
    consensus_text = item["consensus_percent"]
    tips_text = item["tips_summary"] or "current support on the OLBG board"
    event_name = item["event_name"]
    variants = [
        f"**{selection}** should win this one because the current {market.lower()} picture for {event_name} is leaning their way, and the board support behind them is stronger than the alternatives on this cricket slate.",
        f"Backing **{selection}** makes sense here because {event_name} is one of the clearer positions on the current cricket board, with {tips_text} and a stronger market lean than most of the surrounding matches.",
        f"**{selection}** is the pick because this market is already showing firmer support for them, with {consensus_text} backing on the board, and that gives them the cleaner case than the other side right now.",
    ]
    return variants[index % len(variants)]


def write_outputs(target_date: str, predictions: list[dict[str, Any]], fast: bool) -> tuple[Path, Path | None]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = target_date.replace("-", "")
    json_path = OUTPUT_DIR / f"cricket_predictions_{stamp}.json"
    json_path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    if fast:
        return json_path, None

    md_path = OUTPUT_DIR / f"cricket_predictions_{stamp}.md"
    lines = [f"# Cricket Predictions for {target_date}", "", "| Event | Pick | Market | Confidence |", "|---|---|---|---|"]
    for idx, item in enumerate(predictions):
        lines.append(f"| {item['event_name']} | {item['selection']} | {item['market']} | {item['confidence']} |")
        lines.append("")
        lines.append(public_reason(item, idx))
        lines.append("")
    if not predictions:
        lines.extend(["NO BET", "", "No cricket event on the current OLBG board cleared the selection rules."])
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a fast cricket prediction card from the OLBG board.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--min-edge", type=float, default=0.05, help="Minimum edge required to keep a selection.")
    parser.add_argument("--min-consensus", type=float, default=0.60, help="Minimum board consensus required.")
    parser.add_argument("--fast", action="store_true", help="Skip markdown generation and write JSON only.")
    args = parser.parse_args()

    board = load_board()
    predictions: list[dict[str, Any]] = []
    for item in board.get("tip_cards", []):
        if item.get("featured_market") not in ACCEPTED_MARKETS:
            continue
        if not current_or_future(item, args.date):
            continue
        decimal_odds = parse_decimal(item.get("odds") or {})
        if not decimal_odds or decimal_odds <= 1.0:
            continue
        consensus = parse_percent(str(item.get("consensus_percent") or ""))
        if consensus is None or consensus < args.min_consensus:
            continue

        implied = 1.0 / decimal_odds
        probability = board_probability(item, decimal_odds)
        edge = probability - implied
        if edge < args.min_edge:
            continue

        predictions.append(
            {
                "date": args.date,
                "event_id": item.get("event_id"),
                "event_url": str(item.get("event_url") or ""),
                "event_name": str(item["event_name"]),
                "selection": str(item["featured_selection"]),
                "market": str(item["featured_market"]),
                "decimal_odds": decimal_odds,
                "implied_probability": round(implied, 4),
                "model_probability": round(probability, 4),
                "edge": round(edge, 4),
                "consensus_percent": str(item.get("consensus_percent") or ""),
                "tips_summary": str(item.get("tips_summary") or ""),
                "comment_count": int(item.get("comment_count") or 0),
                "confidence": confidence_from_edge(edge),
                "strategy": "baseline",
            }
        )

    predictions.sort(key=lambda row: (row["edge"], row["model_probability"]), reverse=True)
    json_path, md_path = write_outputs(args.date, predictions, args.fast)
    print(f"Generated {len(predictions)} active picks for {args.date}")
    print(f"JSON: {json_path}")
    if md_path is not None:
        print(f"Markdown: {md_path}")
    for item in predictions:
        print(f"{item['event_name']}: {item['selection']} ({item['market']}, confidence={item['confidence']})")


if __name__ == "__main__":
    main()
