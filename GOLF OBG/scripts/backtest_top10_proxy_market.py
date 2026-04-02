from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Tuple


MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def logit(probability: float) -> float:
    probability = clamp(probability, 1e-6, 1 - 1e-6)
    return math.log(probability / (1.0 - probability))


def parse_finish_position(value: str) -> int:
    text = (value or "").strip().upper()
    if not text or text == "-":
        return 999
    if text.startswith("T"):
        text = text[1:]
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 999


def parse_event_end_date(event_dates: str, season: str) -> datetime:
    text = (event_dates or "").strip()
    if not text:
        return datetime(int(season), 12, 31)
    try:
        if " - " in text:
            left, right = text.split(" - ", 1)
            left_parts = left.split()
            month = MONTHS[left_parts[0]]
            year = int(right.split(",")[-1].strip())
            right_core = right.split(",")[0].strip()
            if " " in right_core:
                day = int(right_core.split()[-1])
                month = MONTHS[right_core.split()[0]]
            else:
                day = int(right_core)
            return datetime(year, month, day)
    except Exception:
        pass
    return datetime(int(season), 12, 31)


@dataclass
class PriorStats:
    starts: int
    top10_rate_5: float
    top20_rate_8: float
    made_cut_rate_5: float
    avg_finish_score_8: float
    momentum_score: float


def finish_to_score(position: int, field_size: int) -> float:
    if position >= 999:
        return 0.0
    return clamp(1.0 - ((position - 1) / max(field_size - 1, 1)), 0.0, 1.0)


def compute_prior_stats(history: List[Tuple[int, int]]) -> PriorStats:
    if not history:
        return PriorStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    last5 = history[-5:]
    last8 = history[-8:]

    top10_rate_5 = sum(1 for pos, _ in last5 if pos <= 10) / len(last5)
    top20_rate_8 = sum(1 for pos, _ in last8 if pos <= 20) / len(last8)
    made_cut_rate_5 = sum(1 for pos, _ in last5 if pos < 999) / len(last5)
    avg_finish_score_8 = statistics.mean(finish_to_score(pos, field) for pos, field in last8)

    weighted = 0.0
    weight_sum = 0.0
    for idx, (pos, field_size) in enumerate(reversed(last8), start=1):
        weight = 1.0 / idx
        weighted += finish_to_score(pos, field_size) * weight
        weight_sum += weight
    momentum_score = weighted / weight_sum if weight_sum else 0.0

    return PriorStats(
        starts=len(history),
        top10_rate_5=top10_rate_5,
        top20_rate_8=top20_rate_8,
        made_cut_rate_5=made_cut_rate_5,
        avg_finish_score_8=avg_finish_score_8,
        momentum_score=momentum_score,
    )


def baseline_market_prob(stats: PriorStats, field_size: int) -> float:
    base = clamp(10.0 / max(field_size, 60), 0.03, 0.25)
    if stats.starts < 3:
        return base
    adjustment = (
        0.35 * (stats.top10_rate_5 - base)
        + 0.20 * (stats.top20_rate_8 - 0.20)
        + 0.10 * (stats.made_cut_rate_5 - 0.65)
    )
    return clamp(base + adjustment, 0.02, 0.6)


def advanced_model_prob(stats: PriorStats, field_size: int) -> float:
    base = clamp(10.0 / max(field_size, 60), 0.03, 0.25)
    if stats.starts < 3:
        return base
    signal = (
        1.9 * (stats.top10_rate_5 - base)
        + 1.1 * (stats.top20_rate_8 - 0.20)
        + 0.7 * (stats.made_cut_rate_5 - 0.65)
        + 0.9 * (stats.avg_finish_score_8 - 0.50)
        + 1.2 * (stats.momentum_score - 0.50)
    )
    return clamp(sigmoid(logit(base) + signal), 0.02, 0.75)


def proxy_decimal_odds(market_prob: float, vig: float) -> float:
    implied = clamp(market_prob * (1.0 + vig), 0.02, 0.98)
    return round(1.0 / implied, 4)


def load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(
        key=lambda row: (
            parse_event_end_date(row.get("event_dates", ""), row.get("season", "1900")),
            row.get("tournament_id", ""),
            row.get("player_name", ""),
        )
    )
    return rows


def run_proxy_backtest(
    rows: List[Dict[str, str]],
    min_edge: float,
    vig: float,
    max_bets_per_event: int,
    min_starts: int,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    history: DefaultDict[str, List[Tuple[int, int]]] = defaultdict(list)
    event_groups: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
    event_meta: Dict[str, Tuple[str, str]] = {}

    for row in rows:
        event_id = row.get("tournament_id", "")
        event_groups[event_id].append(row)
        event_meta[event_id] = (row.get("event_name", ""), row.get("event_dates", ""))

    ordered_event_ids = sorted(
        event_groups.keys(),
        key=lambda event_id: parse_event_end_date(event_meta[event_id][1], event_groups[event_id][0].get("season", "1900")),
    )

    bets: List[Dict[str, object]] = []

    for event_id in ordered_event_ids:
        event_rows = event_groups[event_id]
        field_size = len(event_rows)
        scored: List[Dict[str, object]] = []
        for row in event_rows:
            player_name = row.get("player_name", "")
            stats = compute_prior_stats(history[player_name])
            if stats.starts < min_starts:
                continue
            market_prob = baseline_market_prob(stats, field_size)
            model_prob = advanced_model_prob(stats, field_size)
            edge = model_prob - market_prob
            odds = proxy_decimal_odds(market_prob, vig)
            scored.append(
                {
                    "row": row,
                    "starts": stats.starts,
                    "market_prob": market_prob,
                    "model_prob": model_prob,
                    "edge": edge,
                    "proxy_odds": odds,
                }
            )

        qualified = [item for item in scored if item["edge"] >= min_edge]
        qualified.sort(key=lambda item: (item["edge"], item["model_prob"]), reverse=True)

        for item in qualified[:max_bets_per_event]:
            row = item["row"]
            result = 1 if parse_finish_position(row.get("finish_position", "")) <= 10 else 0
            odds = float(item["proxy_odds"])
            profit = (odds - 1.0) if result == 1 else -1.0
            bets.append(
                {
                    "event_name": row.get("event_name", ""),
                    "event_dates": row.get("event_dates", ""),
                    "tournament_id": row.get("tournament_id", ""),
                    "player_name": row.get("player_name", ""),
                    "finish_position": row.get("finish_position", ""),
                    "top10_result": result,
                    "starts": item["starts"],
                    "market_prob_proxy": round(item["market_prob"], 4),
                    "model_prob": round(item["model_prob"], 4),
                    "edge": round(item["edge"], 4),
                    "proxy_odds": odds,
                    "profit": round(profit, 4),
                }
            )

        for row in event_rows:
            player_name = row.get("player_name", "")
            finish_position = parse_finish_position(row.get("finish_position", ""))
            history[player_name].append((finish_position, field_size))

    total_bets = len(bets)
    total_profit = round(sum(float(bet["profit"]) for bet in bets), 4)
    wins = sum(int(bet["top10_result"]) for bet in bets)
    summary = {
        "bets": total_bets,
        "wins": wins,
        "hit_rate": round(wins / total_bets, 4) if total_bets else 0.0,
        "total_profit": total_profit,
        "roi": round(total_profit / total_bets, 4) if total_bets else 0.0,
        "avg_edge": round(statistics.mean(float(bet["edge"]) for bet in bets), 4) if bets else 0.0,
        "avg_proxy_odds": round(statistics.mean(float(bet["proxy_odds"]) for bet in bets), 4) if bets else 0.0,
        "events_bet": len({bet["tournament_id"] for bet in bets}),
    }
    return bets, summary


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest a synthetic golf top-10 market proxy using parsed tournament results only.")
    parser.add_argument("--input", default="data/raw/espn/golf_2023_2026_results.csv", help="Input results CSV.")
    parser.add_argument("--output", default="outputs/top10_proxy_market_report.json", help="Summary JSON output.")
    parser.add_argument("--bets-output", default="outputs/top10_proxy_market_bets.csv", help="Bet-level CSV output.")
    parser.add_argument("--min-edge", type=float, default=0.04, help="Minimum edge over proxy market.")
    parser.add_argument("--vig", type=float, default=0.06, help="Proxy market vig applied to implied probability.")
    parser.add_argument("--max-bets-per-event", type=int, default=2, help="Maximum bets per event.")
    parser.add_argument("--min-starts", type=int, default=4, help="Minimum prior starts before a player can qualify.")
    args = parser.parse_args()

    rows = load_rows(Path(args.input))
    bets, summary = run_proxy_backtest(
        rows=rows,
        min_edge=args.min_edge,
        vig=args.vig,
        max_bets_per_event=args.max_bets_per_event,
        min_starts=args.min_starts,
    )

    write_csv(Path(args.bets_output), bets)
    report = {
        "strategy": "top10_proxy_market_backtest",
        "note": "Synthetic market proxy. Uses only parsed historical results, not real sportsbook closing lines.",
        "config": {
            "min_edge": args.min_edge,
            "vig": args.vig,
            "max_bets_per_event": args.max_bets_per_event,
            "min_starts": args.min_starts,
        },
        "summary": summary,
        "bets_output": args.bets_output,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
