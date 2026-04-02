import argparse
import csv
from pathlib import Path

from snooker_backtest import evaluate_match, summarize


def load_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def frange(start, stop, step):
    value = start
    while value <= stop + 1e-12:
        yield round(value, 6)
        value += step


def main():
    parser = argparse.ArgumentParser(description="Sweep snooker betting thresholds to find profitable settings.")
    parser.add_argument("--data", required=True, help="Scored snooker value CSV")
    parser.add_argument("--edge-start", type=float, default=0.02, help="Minimum edge sweep start")
    parser.add_argument("--edge-stop", type=float, default=0.08, help="Minimum edge sweep stop")
    parser.add_argument("--edge-step", type=float, default=0.01, help="Minimum edge sweep step")
    parser.add_argument("--prob-start", type=float, default=0.50, help="Minimum model probability sweep start")
    parser.add_argument("--prob-stop", type=float, default=0.62, help="Minimum model probability sweep stop")
    parser.add_argument("--prob-step", type=float, default=0.02, help="Minimum model probability sweep step")
    parser.add_argument("--max-short-price", type=float, default=1.45, help="Short-price cutoff")
    parser.add_argument("--short-price-edge", type=float, default=0.08, help="Short-price minimum edge")
    parser.add_argument("--max-odds", type=float, default=0.0, help="Optional maximum odds allowed for a bet")
    parser.add_argument(
        "--require-rankings",
        action="store_true",
        help="Skip matches where rank_a or rank_b is missing or zero.",
    )
    parser.add_argument("--stake", type=float, default=1.0, help="Flat stake per bet")
    parser.add_argument("--min-bets", type=int, default=10, help="Ignore settings with fewer than this many bets")
    parser.add_argument("--top", type=int, default=10, help="How many top settings to print")
    parser.add_argument("--export", default="", help="Optional CSV path for all sweep results")
    args = parser.parse_args()

    rows = load_rows(Path(args.data))
    results = []

    for min_edge in frange(args.edge_start, args.edge_stop, args.edge_step):
        for min_model_prob in frange(args.prob_start, args.prob_stop, args.prob_step):
            placed = []
            for row in rows:
                evaluated = evaluate_match(
                    row=row,
                    min_edge=min_edge,
                    min_model_prob=min_model_prob,
                    max_short_price=args.max_short_price,
                    short_price_edge=args.short_price_edge,
                    max_odds=args.max_odds,
                    require_rankings=args.require_rankings,
                    stake=args.stake,
                )
                if evaluated is not None:
                    placed.append(evaluated)

            summary = summarize(placed, "combo")
            if summary["bets"] < args.min_bets:
                continue

            results.append(
                {
                    "min_edge": f"{min_edge:.3f}",
                    "min_model_prob": f"{min_model_prob:.3f}",
                    "bets": summary["bets"],
                    "wins": summary["wins"],
                    "stake": f"{summary['stake']:.2f}",
                    "profit": f"{summary['profit']:.2f}",
                    "roi_pct": f"{summary['roi_pct']:.2f}",
                    "win_rate_pct": f"{summary['win_rate_pct']:.2f}",
                    "avg_edge_pct": f"{summary['avg_edge_pct']:.2f}",
                    "avg_clv_pct": f"{summary['avg_clv_pct']:.2f}",
                    "avg_odds": f"{summary['avg_odds']:.2f}",
                }
            )

    results.sort(key=lambda row: (float(row["roi_pct"]), float(row["profit"]), int(row["bets"])), reverse=True)

    print(f"Rows tested: {len(rows)}")
    print(f"Threshold combinations kept: {len(results)}")
    print()
    print(
        f"{'Edge':>8} {'Prob':>8} {'Bets':>6} {'Wins':>6} {'Profit':>10} "
        f"{'ROI%':>8} {'Hit%':>8} {'AvgEdge':>9} {'AvgCLV':>8} {'Odds':>8}"
    )
    for row in results[: args.top]:
        print(
            f"{row['min_edge']:>8} {row['min_model_prob']:>8} {int(row['bets']):6d} {int(row['wins']):6d} "
            f"{float(row['profit']):10.2f} {float(row['roi_pct']):8.2f} {float(row['win_rate_pct']):8.2f} "
            f"{float(row['avg_edge_pct']):9.2f} {float(row['avg_clv_pct']):8.2f} {float(row['avg_odds']):8.2f}"
        )

    if args.export:
        fieldnames = [
            "min_edge",
            "min_model_prob",
            "bets",
            "wins",
            "stake",
            "profit",
            "roi_pct",
            "win_rate_pct",
            "avg_edge_pct",
            "avg_clv_pct",
            "avg_odds",
        ]
        with open(args.export, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print()
        print(f"Sweep results exported to: {args.export}")


if __name__ == "__main__":
    main()
