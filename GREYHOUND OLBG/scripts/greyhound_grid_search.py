#!/usr/bin/env python3
"""Run a simple profitability grid search across betting filters."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
from types import SimpleNamespace

from greyhound_backtest import (
    backtest,
    build_features,
    chronological_split,
    fit_standardizer,
    load_rows,
    normalize_by_race,
    predict_probabilities,
    train_logistic_regression,
)


def parse_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grid search profitability filters for the greyhound model.")
    parser.add_argument("--input", required=True, help="Path to normalized historical runner CSV.")
    parser.add_argument("--output", default="outputs/grid_search_results.csv", help="Output CSV for grid results.")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--train-end-date")
    parser.add_argument("--test-start-date")
    parser.add_argument("--min-edge-values", default="0.03,0.05,0.07,0.10")
    parser.add_argument("--min-odds-values", default="2.0,2.5,3.0")
    parser.add_argument("--max-odds-values", default="5.0,6.5,8.0")
    parser.add_argument("--min-gap-values", default="0.02,0.04,0.06")
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument("--l2", type=float, default=0.001)
    parser.add_argument("--min-bets", type=int, default=30, help="Only keep parameter sets with at least this many bets.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    raw_rows = load_rows(args.input)
    featured_rows, _ = build_features(raw_rows)
    split_args = SimpleNamespace(
        train_ratio=args.train_ratio,
        train_end_date=args.train_end_date,
        test_start_date=args.test_start_date,
    )
    train_rows, test_rows = chronological_split(featured_rows, split_args)
    if not train_rows or not test_rows:
        raise ValueError("Training/test split produced an empty partition.")

    train_features = [row["features"] for row in train_rows]
    test_features = [row["features"] for row in test_rows]
    standardizer = fit_standardizer(train_features)
    scaled_train = standardizer.transform(train_features)
    scaled_test = standardizer.transform(test_features)
    train_targets = [row["target"] for row in train_rows]

    weights, bias = train_logistic_regression(
        features=scaled_train,
        targets=train_targets,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2=args.l2,
    )
    raw_probs = predict_probabilities(scaled_test, weights, bias)
    normalized_probs = normalize_by_race(test_rows, raw_probs)

    results = []
    for min_edge, min_odds, max_odds, min_gap in itertools.product(
        parse_list(args.min_edge_values),
        parse_list(args.min_odds_values),
        parse_list(args.max_odds_values),
        parse_list(args.min_gap_values),
    ):
        if min_odds >= max_odds:
            continue

        test_copy = [dict(row) for row in test_rows]
        run_args = SimpleNamespace(
            min_edge=min_edge,
            min_odds=min_odds,
            max_odds=max_odds,
            min_prob_gap=min_gap,
            stake=args.stake,
        )
        _, summary = backtest(test_copy, normalized_probs, run_args)
        if summary["bets"] < args.min_bets:
            continue
        results.append(
            {
                "min_edge": min_edge,
                "min_odds": min_odds,
                "max_odds": max_odds,
                "min_prob_gap": min_gap,
                "bets": summary["bets"],
                "profit": summary["profit"],
                "roi": summary["roi"],
                "strike_rate": summary["strike_rate"],
                "longest_losing_run": summary["longest_losing_run"],
            }
        )

    results.sort(key=lambda row: (row["roi"], row["profit"], row["bets"]), reverse=True)

    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()) if results else [
            "min_edge",
            "min_odds",
            "max_odds",
            "min_prob_gap",
            "bets",
            "profit",
            "roi",
            "strike_rate",
            "longest_losing_run",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(json.dumps(results[:20], indent=2))


if __name__ == "__main__":
    main()
