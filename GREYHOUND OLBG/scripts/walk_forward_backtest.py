#!/usr/bin/env python3
"""Walk-forward backtest for the greyhound winner model."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from types import SimpleNamespace

from greyhound_backtest import (
    backtest,
    build_features,
    fit_standardizer,
    load_rows,
    normalize_by_race,
    predict_probabilities,
    train_logistic_regression,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run walk-forward greyhound backtests.")
    parser.add_argument("--input", required=True, help="Path to normalized historical runner CSV.")
    parser.add_argument("--output-dir", default="outputs/walk_forward", help="Output directory.")
    parser.add_argument("--min-train-days", type=int, default=7, help="Minimum number of unique dates before the first test fold.")
    parser.add_argument("--test-days", type=int, default=3, help="Number of unique dates per test fold.")
    parser.add_argument("--step-days", type=int, default=3, help="How far to advance after each fold.")
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--min-odds", type=float, default=2.5)
    parser.add_argument("--max-odds", type=float, default=8.0)
    parser.add_argument("--min-prob-gap", type=float, default=0.02)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--l2", type=float, default=0.001)
    return parser.parse_args()


def save_csv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    raw_rows = load_rows(args.input)
    featured_rows, feature_names = build_features(raw_rows)
    unique_dates = sorted({row["race_date"] for row in featured_rows})

    if len(unique_dates) < args.min_train_days + args.test_days:
        raise ValueError("Not enough unique dates for the requested walk-forward setup.")

    all_bets: list[dict] = []
    fold_summaries: list[dict] = []
    fold_index = 0

    for start_idx in range(args.min_train_days, len(unique_dates) - args.test_days + 1, args.step_days):
        train_dates = set(unique_dates[:start_idx])
        test_dates = set(unique_dates[start_idx : start_idx + args.test_days])
        train_rows = [row for row in featured_rows if row["race_date"] in train_dates]
        test_rows = [row for row in featured_rows if row["race_date"] in test_dates]
        if not train_rows or not test_rows:
            continue

        standardizer = fit_standardizer([row["features"] for row in train_rows])
        scaled_train = standardizer.transform([row["features"] for row in train_rows])
        scaled_test = standardizer.transform([row["features"] for row in test_rows])
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
        test_copy = [dict(row) for row in test_rows]
        run_args = SimpleNamespace(
            min_edge=args.min_edge,
            min_odds=args.min_odds,
            max_odds=args.max_odds,
            min_prob_gap=args.min_prob_gap,
            stake=args.stake,
        )
        bets, summary = backtest(test_copy, normalized_probs, run_args)

        for bet in bets:
            bet["fold"] = fold_index
        all_bets.extend(bets)
        fold_summaries.append(
            {
                "fold": fold_index,
                "train_start": unique_dates[0],
                "train_end": unique_dates[start_idx - 1],
                "test_start": unique_dates[start_idx],
                "test_end": unique_dates[start_idx + args.test_days - 1],
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
                "bets": summary["bets"],
                "profit": summary["profit"],
                "roi": summary["roi"],
                "strike_rate": summary["strike_rate"],
                "longest_losing_run": summary["longest_losing_run"],
            }
        )
        fold_index += 1

    total_turnover = args.stake * len(all_bets)
    total_profit = round(sum(float(bet["profit"]) for bet in all_bets), 4)
    aggregate = {
        "folds": len(fold_summaries),
        "bets": len(all_bets),
        "profit": total_profit,
        "turnover": round(total_turnover, 4),
        "roi": round(total_profit / total_turnover, 4) if total_turnover else 0.0,
        "strike_rate": round(sum(1 for bet in all_bets if str(bet["won"]).lower() == "true") / len(all_bets), 4) if all_bets else 0.0,
        "params": {
            "min_edge": args.min_edge,
            "min_odds": args.min_odds,
            "max_odds": args.max_odds,
            "min_prob_gap": args.min_prob_gap,
            "min_train_days": args.min_train_days,
            "test_days": args.test_days,
            "step_days": args.step_days,
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "l2": args.l2,
        },
        "feature_names": feature_names,
    }

    by_fold = defaultdict(float)
    for fold in fold_summaries:
        by_fold[fold["fold"]] = fold["profit"]
    aggregate["profitable_folds"] = sum(1 for value in by_fold.values() if value > 0)

    save_csv(os.path.join(args.output_dir, "walk_forward_bets.csv"), all_bets)
    save_csv(os.path.join(args.output_dir, "walk_forward_folds.csv"), fold_summaries)
    with open(os.path.join(args.output_dir, "walk_forward_summary.json"), "w", encoding="utf-8") as handle:
        json.dump({"aggregate": aggregate, "folds": fold_summaries}, handle, indent=2)

    print(json.dumps({"aggregate": aggregate, "folds": fold_summaries}, indent=2))


if __name__ == "__main__":
    main()
