import argparse
import csv
from itertools import product
from pathlib import Path

from f1_backtest import load_rows, load_config, evaluate_market


def frange(start, stop, step):
    current = start
    while current <= stop + 1e-12:
        yield round(current, 6)
        current += step


def summarize_result(result):
    summary = result["summary"]
    return {
        "bets_placed": summary["bets_placed"],
        "wins": summary["wins"],
        "hit_rate": summary["hit_rate"],
        "total_profit": summary["total_profit"],
        "roi": summary["roi"],
    }


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "market",
        "min_edge",
        "min_odds",
        "max_bets_per_race",
        "bets_placed",
        "wins",
        "hit_rate",
        "total_profit",
        "roi",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Tune profitable F1 markets by sweeping thresholds.")
    parser.add_argument(
        "--data",
        default=str(Path("data") / "historical_f1_driver_markets_from_guides_2020_2025.csv"),
    )
    parser.add_argument(
        "--config",
        default=str(Path("config") / "market_configs_profit_focus.json"),
    )
    parser.add_argument(
        "--output",
        default=str(Path("data") / "analysis" / "profit_market_sweep.csv"),
    )
    parser.add_argument("--min-train-races", type=int, default=12)
    parser.add_argument("--bankroll", type=float, default=1000.0)
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument(
        "--markets",
        nargs="+",
        default=None,
        help="Optional subset of markets to tune.",
    )
    args = parser.parse_args()

    rows = load_rows(args.data)
    markets = load_config(args.config)
    if args.markets:
        selected = set(args.markets)
        markets = {name: config for name, config in markets.items() if name in selected}

    sweep_rows = []
    for market_name, market_config in markets.items():
        if market_name == "podium_finish":
            edge_values = [0.04, 0.06, 0.08, 0.10]
            odds_values = [2.0, 3.0, 4.0]
            max_bets_values = [1, 2]
        else:
            edge_values = [0.06, 0.08, 0.10, 0.12]
            odds_values = [5.0, 7.0, 10.0]
            max_bets_values = [1]

        for min_edge, min_odds, max_bets in product(edge_values, odds_values, max_bets_values):
            tuned_config = dict(market_config)
            tuned_config["min_edge"] = min_edge
            tuned_config["min_odds"] = min_odds
            tuned_config["max_bets_per_race"] = max_bets
            result = evaluate_market(
                rows=rows,
                market_name=market_name,
                market_config=tuned_config,
                min_train_races=args.min_train_races,
                bankroll=args.bankroll,
                iterations=args.iterations,
            )
            summary = summarize_result(result)
            if summary["bets_placed"] == 0:
                continue
            sweep_rows.append(
                {
                    "market": market_name,
                    "min_edge": min_edge,
                    "min_odds": min_odds,
                    "max_bets_per_race": max_bets,
                    **summary,
                }
            )

    sweep_rows.sort(
        key=lambda row: (
            row["market"],
            row["roi"],
            row["total_profit"],
            row["bets_placed"],
        ),
        reverse=True,
    )
    write_csv(sweep_rows, Path(args.output))

    print(f"Wrote {len(sweep_rows)} sweep rows to {args.output}")
    for market in sorted({row["market"] for row in sweep_rows}):
        market_rows = [row for row in sweep_rows if row["market"] == market]
        top_rows = sorted(
            market_rows,
            key=lambda row: (row["roi"], row["total_profit"], row["bets_placed"]),
            reverse=True,
        )[:5]
        print(f"\n=== {market} top settings ===")
        for row in top_rows:
            print(
                f"edge={row['min_edge']:.2f} odds>={row['min_odds']:.2f} "
                f"max_bets={row['max_bets_per_race']} bets={row['bets_placed']} "
                f"wins={row['wins']} roi={row['roi']:.2%} profit={row['total_profit']:.2f}"
            )


if __name__ == "__main__":
    main()
