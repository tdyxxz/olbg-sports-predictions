from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"


def logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1.0 - probability))


def settle_decimal(decimal_odds: float, won: bool) -> float:
    return round(decimal_odds - 1.0, 4) if won else -1.0


def odds_band_match(home_prob: float, band: str) -> bool:
    if band == "all":
        return True
    if band == "favorites":
        return home_prob >= 0.55 or home_prob <= 0.45
    if band == "coinflip":
        return 0.45 < home_prob < 0.55
    if band == "strong_favorites":
        return home_prob >= 0.62 or home_prob <= 0.38
    return True


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def to_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def score_home_probability(row: dict[str, str]) -> float:
    base = logit(to_float(row, "home_implied_prob"))
    base += 1.00 * to_float(row, "overall_win_pct_edge")
    base += 0.85 * to_float(row, "venue_win_pct_edge")
    base += 0.90 * to_float(row, "recent_win_pct_edge")
    base += 0.050 * to_float(row, "season_point_diff_edge")
    base += 0.060 * to_float(row, "recent_point_diff_edge")
    return logistic(base)


def run_backtest(rows: list[dict[str, str]], min_edge: float, band: str) -> dict[str, Any]:
    bets: list[dict[str, Any]] = []
    profit = 0.0
    for row in rows:
        implied_home = to_float(row, "home_implied_prob")
        model_home = score_home_probability(row)
        if not odds_band_match(implied_home, band):
            continue

        home_edge = model_home - implied_home
        away_edge = (1.0 - model_home) - (1.0 - implied_home)
        if max(home_edge, away_edge) < min_edge:
            continue

        if home_edge >= away_edge:
            selection = row["home_team"]
            decimal_odds = to_float(row, "home_decimal_odds")
            won = int(row["home_win"]) == 1
            selection_prob = model_home
            edge = home_edge
        else:
            selection = row["away_team"]
            decimal_odds = to_float(row, "away_decimal_odds")
            won = int(row["home_win"]) == 0
            selection_prob = 1.0 - model_home
            edge = away_edge

        bet_profit = settle_decimal(decimal_odds, won)
        profit += bet_profit
        bets.append(
            {
                "date": row["date"],
                "matchup": f"{row['away_team']} at {row['home_team']}",
                "selection": selection,
                "decimal_odds": round(decimal_odds, 4),
                "model_probability": round(selection_prob, 4),
                "edge": round(edge, 4),
                "won": won,
                "profit": bet_profit,
            }
        )

    total_bets = len(bets)
    wins = sum(1 for bet in bets if bet["won"])
    return {
        "band": band,
        "min_edge": min_edge,
        "bets": total_bets,
        "wins": wins,
        "losses": total_bets - wins,
        "profit": round(profit, 4),
        "roi": round((profit / total_bets) if total_bets else 0.0, 4),
        "win_rate": round((wins / total_bets) if total_bets else 0.0, 4),
        "bet_log": bets,
    }


def write_report(path: Path, best: dict[str, Any], all_results: list[dict[str, Any]]) -> None:
    lines = [
        "# NBA Moneyline Backtest",
        "",
        f"- Best band: {best['band']}",
        f"- Minimum edge: {best['min_edge']:.2f}",
        f"- Bets: {best['bets']}",
        f"- Wins: {best['wins']}",
        f"- Losses: {best['losses']}",
        f"- Profit: {best['profit']:.4f} units",
        f"- ROI: {best['roi']:.4f}",
        f"- Win Rate: {best['win_rate']:.4f}",
        "",
        "## Grid",
        "",
        "| Band | Min Edge | Bets | Profit | ROI | Win Rate |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in all_results:
        lines.append(
            f"| {item['band']} | {item['min_edge']:.2f} | {item['bets']} | {item['profit']:.4f} | {item['roi']:.4f} | {item['win_rate']:.4f} |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest a first-pass NBA moneyline model from the local feature dataset.")
    parser.add_argument("--input-csv", default=str(OUTPUT_DIR / "nba_moneyline_feature_dataset.csv"))
    parser.add_argument("--output-json", default=str(OUTPUT_DIR / "nba_moneyline_backtest.json"))
    parser.add_argument("--output-md", default=str(OUTPUT_DIR / "nba_moneyline_backtest.md"))
    args = parser.parse_args()

    rows = load_rows(Path(args.input_csv))
    grid: list[dict[str, Any]] = []
    for band in ("all", "favorites", "coinflip", "strong_favorites"):
        for min_edge in (0.02, 0.04, 0.06, 0.08):
            grid.append(run_backtest(rows, min_edge=min_edge, band=band))

    best = max(grid, key=lambda item: (item["profit"], item["roi"], item["bets"]))
    payload = {"best": best, "grid": grid}

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(output_md, best=best, all_results=grid)
    print(f"JSON: {output_json}")
    print(f"Markdown: {output_md}")
    print(json.dumps({k: best[k] for k in ('band', 'min_edge', 'bets', 'profit', 'roi')}, indent=2))


if __name__ == "__main__":
    main()
