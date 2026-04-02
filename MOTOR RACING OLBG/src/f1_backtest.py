import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def sigmoid(value):
    if isinstance(value, np.ndarray):
        clipped = np.clip(value, -50.0, 50.0)
        return 1.0 / (1.0 + np.exp(-clipped))
    if value >= 0:
        exp_neg = math.exp(-value)
        return 1.0 / (1.0 + exp_neg)
    exp_pos = math.exp(value)
    return exp_pos / (1.0 + exp_pos)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            row["season"] = int(row["season"])
            row["round"] = int(row["round"])
            rows.append(row)
    rows.sort(key=lambda item: (item["season"], item["round"], item["driver"]))
    return rows


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as handle:
        return json.load(handle)["markets"]


def collect_feature_stats(rows, features):
    stats = {}
    for feature in features:
        values = [safe_float(row.get(feature, 0.0)) for row in rows]
        if not values:
            stats[feature] = {"mean": 0.0, "std": 1.0}
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        std = math.sqrt(variance) or 1.0
        stats[feature] = {"mean": mean, "std": std}
    return stats


def vectorize(row, features, stats):
    values = [1.0]
    for feature in features:
        raw = safe_float(row.get(feature, 0.0))
        mean = stats[feature]["mean"]
        std = stats[feature]["std"]
        values.append((raw - mean) / std)
    return values


def build_matrix(rows, features, stats, label_column=None):
    if not rows:
        x_empty = np.zeros((0, len(features) + 1), dtype=float)
        if label_column is None:
            return x_empty
        return x_empty, np.zeros((0,), dtype=float)

    matrix = np.ones((len(rows), len(features) + 1), dtype=float)
    for feature_index, feature in enumerate(features, start=1):
        mean = stats[feature]["mean"]
        std = stats[feature]["std"]
        matrix[:, feature_index] = [
            (safe_float(row.get(feature, 0.0)) - mean) / std for row in rows
        ]

    if label_column is None:
        return matrix
    labels = np.array([safe_float(row[label_column]) for row in rows], dtype=float)
    return matrix, labels


def fit_logistic_regression(
    rows,
    features,
    label_column,
    iterations=120,
    lr=0.06,
    l2=0.002,
    initial_weights=None,
):
    stats = collect_feature_stats(rows, features)
    if not rows:
        return np.zeros(len(features) + 1, dtype=float), stats

    x_matrix, y_vector = build_matrix(rows, features, stats, label_column=label_column)
    if initial_weights is None or len(initial_weights) != len(features) + 1:
        weights = np.zeros(len(features) + 1, dtype=float)
    else:
        weights = np.array(initial_weights, dtype=float)

    for _ in range(iterations):
        scores = x_matrix @ weights
        predictions = sigmoid(scores)
        errors = predictions - y_vector
        gradients = (x_matrix.T @ errors) / float(len(rows))
        gradients[1:] += l2 * weights[1:]
        weights -= lr * gradients

    return weights, stats


def predict_probabilities(rows, weights, features, stats):
    x_matrix = build_matrix(rows, features, stats)
    return sigmoid(x_matrix @ weights)


def decimal_to_implied_prob(odds):
    odds_value = safe_float(odds)
    if odds_value <= 1.0:
        return None
    return 1.0 / odds_value


def expected_value(probability, odds):
    odds_value = safe_float(odds)
    if odds_value <= 1.0:
        return None
    return (probability * odds_value) - 1.0


def group_rows_by_race(rows):
    grouped = defaultdict(list)
    for row in rows:
        key = (row["season"], row["round"], row["race_name"])
        grouped[key].append(row)
    return grouped


def evaluate_market(rows, market_name, market_config, min_train_races, bankroll, iterations):
    features = market_config["features"]
    label_column = market_config["label_column"]
    odds_column = market_config["odds_column"]
    min_edge = safe_float(market_config["min_edge"])
    min_odds = safe_float(market_config["min_odds"])
    max_bets_per_race = int(market_config["max_bets_per_race"])

    races = sorted(group_rows_by_race(rows).items(), key=lambda item: item[0])
    train_rows = []
    evaluated_races = 0
    bets = []
    weights = None

    for race_key, race_rows in races:
        if evaluated_races < min_train_races:
            train_rows.extend(race_rows)
            evaluated_races += 1
            continue

        weights, stats = fit_logistic_regression(
            train_rows,
            features,
            label_column,
            iterations=iterations,
            initial_weights=weights,
        )
        race_probabilities = predict_probabilities(race_rows, weights, features, stats)
        race_candidates = []
        for row, probability in zip(race_rows, race_probabilities):
            odds = safe_float(row.get(odds_column, 0.0))
            if odds < min_odds:
                continue

            implied_prob = decimal_to_implied_prob(odds)
            if implied_prob is None:
                continue
            edge = probability - implied_prob
            ev = expected_value(probability, odds)
            if edge >= min_edge and ev is not None and ev > 0:
                race_candidates.append(
                    {
                        "season": row["season"],
                        "round": row["round"],
                        "race_name": row["race_name"],
                        "driver": row["driver"],
                        "team": row["team"],
                        "odds": odds,
                        "probability": probability,
                        "implied_prob": implied_prob,
                        "edge": edge,
                        "ev": ev,
                        "won": int(safe_float(row[label_column])),
                    }
                )

        race_candidates.sort(key=lambda item: (item["edge"], item["ev"]), reverse=True)
        selected = race_candidates[:max_bets_per_race]
        for candidate in selected:
            stake = 1.0
            profit = (candidate["odds"] - 1.0) * stake if candidate["won"] else -stake
            candidate["stake"] = stake
            candidate["profit"] = profit
            bets.append(candidate)

        train_rows.extend(race_rows)
        evaluated_races += 1

    total_staked = sum(bet["stake"] for bet in bets)
    total_profit = sum(bet["profit"] for bet in bets)
    wins = sum(bet["won"] for bet in bets)
    roi = (total_profit / total_staked) if total_staked else 0.0
    hit_rate = (wins / len(bets)) if bets else 0.0
    ending_bankroll = bankroll + total_profit

    by_season = defaultdict(lambda: {"bets": 0, "profit": 0.0})
    for bet in bets:
        bucket = by_season[bet["season"]]
        bucket["bets"] += 1
        bucket["profit"] += bet["profit"]

    return {
        "market": market_name,
        "bets": bets,
        "summary": {
            "bets_placed": len(bets),
            "wins": wins,
            "hit_rate": hit_rate,
            "total_staked": total_staked,
            "total_profit": total_profit,
            "roi": roi,
            "starting_bankroll": bankroll,
            "ending_bankroll": ending_bankroll,
        },
        "by_season": dict(by_season),
    }


def print_market_report(result):
    summary = result["summary"]
    print(f"\n=== {result['market']} ===")
    print(f"Bets placed     : {summary['bets_placed']}")
    print(f"Wins            : {summary['wins']}")
    print(f"Hit rate        : {summary['hit_rate']:.2%}")
    print(f"Total staked    : {summary['total_staked']:.2f}")
    print(f"Total profit    : {summary['total_profit']:.2f}")
    print(f"ROI             : {summary['roi']:.2%}")
    print(f"Ending bankroll : {summary['ending_bankroll']:.2f}")
    if result["by_season"]:
        print("Profit by season:")
        for season, season_data in sorted(result["by_season"].items()):
            print(
                f"  {season}: bets={season_data['bets']} "
                f"profit={season_data['profit']:.2f}"
            )

    if result["bets"]:
        print("Sample bets:")
        for bet in result["bets"][:5]:
            print(
                "  "
                f"{bet['season']} R{bet['round']} {bet['race_name']} | "
                f"{bet['driver']} | odds {bet['odds']:.2f} | "
                f"model {bet['probability']:.2%} | edge {bet['edge']:.2%} | "
                f"profit {bet['profit']:.2f}"
            )


def main():
    parser = argparse.ArgumentParser(description="Backtest F1 driver betting markets.")
    parser.add_argument(
        "--data",
        default=str(Path("data") / "historical_f1_driver_markets.csv"),
        help="Path to the historical driver market CSV.",
    )
    parser.add_argument(
        "--config",
        default=str(Path("config") / "market_configs.json"),
        help="Path to the JSON config file.",
    )
    parser.add_argument(
        "--min-train-races",
        type=int,
        default=8,
        help="Number of races to reserve for initial training before walk-forward evaluation.",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        default=1000.0,
        help="Starting bankroll used in reporting.",
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=None,
        help="Optional subset of market names to evaluate.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=120,
        help="Gradient-descent iterations per walk-forward refit.",
    )
    args = parser.parse_args()

    rows = load_rows(args.data)
    markets = load_config(args.config)
    if args.markets:
        selected = set(args.markets)
        markets = {name: config for name, config in markets.items() if name in selected}

    print(f"Loaded {len(rows)} driver-race rows from {args.data}")
    for market_name, market_config in markets.items():
        result = evaluate_market(
            rows=rows,
            market_name=market_name,
            market_config=market_config,
            min_train_races=args.min_train_races,
            bankroll=args.bankroll,
            iterations=args.iterations,
        )
        print_market_report(result)


if __name__ == "__main__":
    main()
