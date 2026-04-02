from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_SAMPLE_PATH = OUTPUT_DIR / "historical_cricket_sample.json"


def settle(decimal_odds: float, won: bool) -> float:
    return round(decimal_odds - 1.0, 4) if won else -1.0


def favorite_side(row: dict[str, Any]) -> tuple[str, float, float]:
    home_odds = float(row["home_decimal_odds"])
    away_odds = float(row["away_decimal_odds"])
    if home_odds <= away_odds:
        return "home", home_odds, away_odds
    return "away", away_odds, home_odds


def backtest_rows(rows: list[dict[str, Any]], max_favorite_odds: float, min_gap: float) -> dict[str, Any]:
    bets: list[dict[str, Any]] = []
    for row in rows:
        side, favorite_odds, other_odds = favorite_side(row)
        if favorite_odds > max_favorite_odds:
            continue
        if (other_odds - favorite_odds) < min_gap:
            continue
        selection = row["home_team"] if side == "home" else row["away_team"]
        won = selection == row["winner"]
        bets.append(
            {
                "date": row["date_utc"],
                "competition": row["competition"],
                "match_url": row["match_url"],
                "selection": selection,
                "winner": row["winner"],
                "decimal_odds": favorite_odds,
                "won": won,
                "profit": settle(favorite_odds, won),
            }
        )

    profit = round(sum(item["profit"] for item in bets), 4)
    bet_count = len(bets)
    return {
        "bets": bet_count,
        "wins": sum(1 for item in bets if item["won"]),
        "losses": sum(1 for item in bets if not item["won"]),
        "profit": profit,
        "roi": round((profit / bet_count) if bet_count else 0.0, 4),
        "win_rate": round((sum(1 for item in bets if item["won"]) / bet_count) if bet_count else 0.0, 4),
        "picks": bets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small favorite-based cricket moneyline backtest.")
    parser.add_argument("--sample-json", default=str(DEFAULT_SAMPLE_PATH))
    parser.add_argument("--output-json", default=str(OUTPUT_DIR / "cricket_moneyline_backtest.json"))
    parser.add_argument("--output-md", default=str(OUTPUT_DIR / "cricket_moneyline_backtest.md"))
    args = parser.parse_args()

    rows = json.loads(Path(args.sample_json).read_text(encoding="utf-8"))
    grid: list[dict[str, Any]] = []
    for max_odds in (1.55, 1.7, 1.85, 2.0, 2.15, 2.3):
        for min_gap in (0.0, 0.1, 0.2, 0.3, 0.4):
            summary = backtest_rows(rows, max_odds, min_gap)
            grid.append(
                {
                    "max_favorite_odds": max_odds,
                    "min_gap": min_gap,
                    **summary,
                }
            )

    best = max(grid, key=lambda item: (item["profit"], item["roi"], item["bets"]))
    payload = {
        "sample_size": len(rows),
        "best_regime": best,
        "grid": grid,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Cricket Moneyline Backtest",
        "",
        f"- Sample Size: {len(rows)}",
        f"- Best Max Favorite Odds: {best['max_favorite_odds']:.2f}",
        f"- Best Minimum Odds Gap: {best['min_gap']:.2f}",
        f"- Bets: {best['bets']}",
        f"- Wins: {best['wins']}",
        f"- Losses: {best['losses']}",
        f"- Profit: {best['profit']:.4f} units",
        f"- ROI: {best['roi']:.4f}",
        f"- Win Rate: {best['win_rate']:.4f}",
        "",
    ]
    output_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"JSON: {output_json}")
    print(f"Markdown: {output_md}")
    print(json.dumps({"sample_size": len(rows), "best_profit": best["profit"], "best_roi": best["roi"]}, indent=2))


if __name__ == "__main__":
    main()
