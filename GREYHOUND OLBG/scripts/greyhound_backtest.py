#!/usr/bin/env python3
"""Profitability-first greyhound winner model and backtester.

Input: one CSV row per runner per race.
Output: a summary JSON file and a bets CSV file.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Tuple


EPSILON = 1e-9


@dataclass
class Standardizer:
    means: List[float]
    stds: List[float]

    def transform(self, rows: Sequence[Sequence[float]]) -> List[List[float]]:
        transformed = []
        for row in rows:
            transformed.append(
                [
                    0.0 if self.stds[i] < EPSILON else (float(value) - self.means[i]) / self.stds[i]
                    for i, value in enumerate(row)
                ]
            )
        return transformed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest a greyhound win model from historical runner data.")
    parser.add_argument("--input", required=True, help="Path to normalized historical runner CSV.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for summary and bet exports.")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="Chronological training split if no dates supplied.")
    parser.add_argument("--train-end-date", help="Last training date in YYYY-MM-DD.")
    parser.add_argument("--test-start-date", help="First test date in YYYY-MM-DD.")
    parser.add_argument("--min-edge", type=float, default=0.05, help="Minimum model minus market probability edge.")
    parser.add_argument("--min-odds", type=float, default=2.0, help="Minimum decimal odds.")
    parser.add_argument("--max-odds", type=float, default=6.5, help="Maximum decimal odds.")
    parser.add_argument("--min-prob-gap", type=float, default=0.04, help="Minimum probability gap over second choice.")
    parser.add_argument("--stake", type=float, default=1.0, help="Flat stake per bet.")
    parser.add_argument("--learning-rate", type=float, default=0.05, help="Gradient descent learning rate.")
    parser.add_argument("--epochs", type=int, default=400, help="Training epochs.")
    parser.add_argument("--l2", type=float, default=0.001, help="L2 regularization strength.")
    return parser.parse_args()


def to_float(value: str, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except ValueError:
        return default


def to_int(value: str, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except ValueError:
        return default


def parse_date(value: str) -> datetime:
    return datetime.strptime(value[:10], "%Y-%m-%d")


def fractional_to_decimal(value: str) -> float:
    value = (value or "").strip().lower().replace("jf", "").replace("f", "")
    if not value:
        return 0.0
    if "/" in value:
        left, right = value.split("/", 1)
        try:
            return float(left) / float(right) + 1.0
        except ValueError:
            return 0.0
    return to_float(value, default=0.0)


def extract_decimal_odds(row: dict) -> float:
    sp = to_float(row.get("sp_decimal", ""), default=0.0)
    if sp > 1.01:
        return sp
    isp = fractional_to_decimal(row.get("isp", ""))
    if isp > 1.01:
        return isp
    return max(sp, 0.0)


def safe_mean(values: Iterable[float], default: float = 0.0) -> float:
    values = list(values)
    return statistics.fmean(values) if values else default


def fraction_wins(rows: Sequence[dict]) -> float:
    return safe_mean(1.0 if to_int(row["finish_pos"]) == 1 else 0.0 for row in rows)


def fraction_places(rows: Sequence[dict]) -> float:
    return safe_mean(1.0 if 0 < to_int(row["finish_pos"]) <= 3 else 0.0 for row in rows)


def avg_finish(rows: Sequence[dict], default: float = 6.0) -> float:
    finishes = [to_int(row["finish_pos"]) for row in rows if to_int(row["finish_pos"]) > 0]
    return safe_mean(finishes, default=default)


def clamp_probability(value: float) -> float:
    return min(max(value, 0.001), 0.999)


def grade_to_strength(grade: str) -> float:
    grade = (grade or "").upper().strip()
    if not grade:
        return 5.0

    if grade.startswith("OR"):
        base = 0.0
        suffix = grade[2:]
    else:
        ladder = {
            "A": 1.0,
            "D": 1.5,
            "S": 2.0,
            "B": 3.0,
            "T": 0.5,
            "H": 2.5,
        }
        base = ladder.get(grade[0], 4.0)
        suffix = grade[1:]

    number = 0.0
    digits = "".join(ch for ch in suffix if ch.isdigit())
    if digits:
        number = float(digits) / 10.0
    return base + number


def build_features(rows: List[dict]) -> Tuple[List[dict], List[str]]:
    rows = sorted(rows, key=lambda row: (parse_date(row["race_date"]), row["race_id"], row["dog_name"]))

    dog_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
    dog_track_history: Dict[Tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=10))
    dog_trap_history: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=10))
    dog_distance_history: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=10))
    track_distance_times: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=200))
    race_sizes: Dict[str, int] = defaultdict(int)

    for row in rows:
        race_sizes[row["race_id"]] += 1

    feature_names = [
        "market_prob",
        "log_sp",
        "field_size",
        "trap_number",
        "recent_win_rate_5",
        "recent_place_rate_5",
        "recent_avg_finish_5",
        "weighted_recent_win",
        "track_win_rate",
        "trap_win_rate",
        "distance_win_rate",
        "days_since_last",
        "days_since_win",
        "grade_relief",
        "distance_change",
        "split_advantage",
        "time_advantage",
    ]

    featured_rows = []
    last_race_date_by_dog: Dict[str, datetime] = {}
    last_win_date_by_dog: Dict[str, datetime] = {}
    last_distance_by_dog: Dict[str, int] = {}
    last_grade_strength_by_dog: Dict[str, float] = {}

    for row in rows:
        dog = row["dog_name"]
        track = row["track"]
        trap = to_int(row["trap"], default=0)
        distance = to_int(row["distance_m"], default=0)
        race_date = parse_date(row["race_date"])
        sp = max(extract_decimal_odds(row), 1.01)
        market_prob = clamp_probability(1.0 / sp)

        recent = list(dog_history[dog])[-5:]
        track_recent = list(dog_track_history[(dog, track)])
        trap_recent = list(dog_trap_history[(dog, trap)])
        distance_recent = list(dog_distance_history[(dog, distance)])

        weighted_recent = 0.0
        weights = [3, 2, 1, 1, 1]
        for index, prior in enumerate(reversed(recent)):
            weight = weights[index] if index < len(weights) else 1
            weighted_recent += weight * (1.0 if to_int(prior["finish_pos"]) == 1 else 0.0)
        weighted_recent /= sum(weights[: len(recent)]) if recent else 1.0

        days_since_last = 30.0
        if dog in last_race_date_by_dog:
            days_since_last = float((race_date - last_race_date_by_dog[dog]).days)

        days_since_win = 60.0
        if dog in last_win_date_by_dog:
            days_since_win = float((race_date - last_win_date_by_dog[dog]).days)

        grade_strength = grade_to_strength(row["grade"])
        grade_relief = 0.0
        if dog in last_grade_strength_by_dog:
            grade_relief = last_grade_strength_by_dog[dog] - grade_strength

        distance_change = 0.0
        if dog in last_distance_by_dog:
            distance_change = float(distance - last_distance_by_dog[dog])

        split_time = to_float(row.get("split_time", ""), default=0.0)
        run_time = to_float(row.get("run_time", ""), default=0.0)
        prior_times = list(track_distance_times[(track, distance)])
        par_split = safe_mean((item["split_time"] for item in prior_times if item["split_time"] > 0), default=0.0)
        par_time = safe_mean((item["run_time"] for item in prior_times if item["run_time"] > 0), default=0.0)

        split_advantage = 0.0
        if split_time > 0 and par_split > 0:
            split_advantage = par_split - split_time

        time_advantage = 0.0
        if run_time > 0 and par_time > 0:
            time_advantage = par_time - run_time

        feature_vector = [
            market_prob,
            math.log(sp),
            float(race_sizes[row["race_id"]]),
            float(trap),
            fraction_wins(recent),
            fraction_places(recent),
            avg_finish(recent),
            weighted_recent,
            fraction_wins(track_recent),
            fraction_wins(trap_recent),
            fraction_wins(distance_recent),
            days_since_last,
            days_since_win,
            grade_relief,
            distance_change,
            split_advantage,
            time_advantage,
        ]

        enriched = dict(row)
        enriched["features"] = feature_vector
        enriched["target"] = 1 if to_int(row["finish_pos"]) == 1 else 0
        featured_rows.append(enriched)

        dog_history[dog].append(row)
        dog_track_history[(dog, track)].append(row)
        dog_trap_history[(dog, trap)].append(row)
        dog_distance_history[(dog, distance)].append(row)
        track_distance_times[(track, distance)].append({"split_time": split_time, "run_time": run_time})
        last_race_date_by_dog[dog] = race_date
        last_distance_by_dog[dog] = distance
        last_grade_strength_by_dog[dog] = grade_strength
        if to_int(row["finish_pos"]) == 1:
            last_win_date_by_dog[dog] = race_date

    return featured_rows, feature_names


def chronological_split(rows: List[dict], args: argparse.Namespace) -> Tuple[List[dict], List[dict]]:
    if args.train_end_date or args.test_start_date:
        train_end = parse_date(args.train_end_date) if args.train_end_date else None
        test_start = parse_date(args.test_start_date) if args.test_start_date else None
        train, test = [], []
        for row in rows:
            race_date = parse_date(row["race_date"])
            if train_end and race_date <= train_end:
                train.append(row)
            elif test_start and race_date >= test_start:
                test.append(row)
            elif not train_end and test_start and race_date < test_start:
                train.append(row)
            elif train_end and not test_start and race_date > train_end:
                test.append(row)
        return train, test

    dates = sorted({row["race_date"] for row in rows})
    split_index = max(1, int(len(dates) * args.train_ratio))
    train_dates = set(dates[:split_index])
    train = [row for row in rows if row["race_date"] in train_dates]
    test = [row for row in rows if row["race_date"] not in train_dates]
    return train, test


def fit_standardizer(rows: Sequence[Sequence[float]]) -> Standardizer:
    columns = list(zip(*rows))
    means = [safe_mean(column) for column in columns]
    stds = []
    for index, column in enumerate(columns):
        variance = safe_mean((value - means[index]) ** 2 for value in column)
        stds.append(math.sqrt(variance))
    return Standardizer(means=means, stds=stds)


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def train_logistic_regression(
    features: List[List[float]],
    targets: List[int],
    learning_rate: float,
    epochs: int,
    l2: float,
) -> Tuple[List[float], float]:
    if not features:
        raise ValueError("No training rows available.")

    num_features = len(features[0])
    weights = [0.0] * num_features
    bias = 0.0
    sample_count = float(len(features))

    for _ in range(epochs):
        grad_w = [0.0] * num_features
        grad_b = 0.0
        for row, target in zip(features, targets):
            prediction = sigmoid(sum(weight * value for weight, value in zip(weights, row)) + bias)
            error = prediction - float(target)
            for i, value in enumerate(row):
                grad_w[i] += error * value
            grad_b += error

        for i in range(num_features):
            grad_w[i] = grad_w[i] / sample_count + (l2 * weights[i])
            weights[i] -= learning_rate * grad_w[i]
        bias -= learning_rate * (grad_b / sample_count)

    return weights, bias


def predict_probabilities(features: List[List[float]], weights: List[float], bias: float) -> List[float]:
    return [sigmoid(sum(weight * value for weight, value in zip(weights, row)) + bias) for row in features]


def normalize_by_race(rows: List[dict], raw_probs: List[float]) -> List[float]:
    grouped: Dict[str, List[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[row["race_id"]].append(index)

    normalized = [0.0] * len(rows)
    for indices in grouped.values():
        total = sum(raw_probs[index] for index in indices)
        total = total if total > EPSILON else float(len(indices))
        for index in indices:
            normalized[index] = raw_probs[index] / total if total > EPSILON else 1.0 / len(indices)
    return normalized


def longest_losing_run(results: Sequence[float]) -> int:
    longest = 0
    current = 0
    for value in results:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def bucket_label(value: float, cut_points: Sequence[float]) -> str:
    for point in cut_points:
        if value < point:
            return f"<{point:.2f}"
    return f">={cut_points[-1]:.2f}"


def backtest(rows: List[dict], normalized_probs: List[float], args: argparse.Namespace) -> Tuple[List[dict], dict]:
    for row, prob in zip(rows, normalized_probs):
        row["model_prob"] = prob
        odds_value = max(extract_decimal_odds(row), 1.01)
        row["market_prob"] = clamp_probability(1.0 / odds_value)
        row["edge"] = row["model_prob"] - row["market_prob"]

    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["race_id"]].append(row)

    bets = []
    pnl_values = []
    by_track = defaultdict(lambda: {"bets": 0, "profit": 0.0})
    by_edge = defaultdict(lambda: {"bets": 0, "profit": 0.0})
    by_odds = defaultdict(lambda: {"bets": 0, "profit": 0.0})

    for race_id, race_rows in grouped.items():
        ranked = sorted(race_rows, key=lambda row: row["model_prob"], reverse=True)
        top = ranked[0]
        second_prob = ranked[1]["model_prob"] if len(ranked) > 1 else 0.0
        prob_gap = top["model_prob"] - second_prob
        odds = extract_decimal_odds(top)

        qualifies = (
            top["edge"] >= args.min_edge
            and args.min_odds <= odds <= args.max_odds
            and prob_gap >= args.min_prob_gap
        )
        if not qualifies:
            continue

        won = to_int(top["finish_pos"]) == 1
        profit = args.stake * (odds - 1.0) if won else -args.stake
        pnl_values.append(profit)

        bet = {
            "race_id": race_id,
            "race_date": top["race_date"],
            "track": top["track"],
            "dog_name": top["dog_name"],
            "sp_decimal": round(odds, 4),
            "finish_pos": to_int(top["finish_pos"]),
            "won": won,
            "profit": round(profit, 4),
            "model_prob": round(top["model_prob"], 4),
            "market_prob": round(top["market_prob"], 4),
            "edge": round(top["edge"], 4),
            "prob_gap": round(prob_gap, 4),
        }
        bets.append(bet)

        by_track[top["track"]]["bets"] += 1
        by_track[top["track"]]["profit"] += profit

        edge_bucket = bucket_label(top["edge"], [0.05, 0.08, 0.12])
        by_edge[edge_bucket]["bets"] += 1
        by_edge[edge_bucket]["profit"] += profit

        odds_bucket = bucket_label(odds, [2.5, 4.0, 6.5])
        by_odds[odds_bucket]["bets"] += 1
        by_odds[odds_bucket]["profit"] += profit

    turnover = args.stake * len(bets)
    total_profit = sum(pnl_values)
    summary = {
        "bets": len(bets),
        "turnover": round(turnover, 4),
        "profit": round(total_profit, 4),
        "roi": round(total_profit / turnover, 4) if turnover else 0.0,
        "strike_rate": round(sum(1 for bet in bets if bet["won"]) / len(bets), 4) if bets else 0.0,
        "longest_losing_run": longest_losing_run(pnl_values),
        "by_track": {
            key: {"bets": value["bets"], "profit": round(value["profit"], 4), "roi": round(value["profit"] / value["bets"], 4)}
            for key, value in sorted(by_track.items())
        },
        "by_edge_bucket": {
            key: {"bets": value["bets"], "profit": round(value["profit"], 4), "roi": round(value["profit"] / value["bets"], 4)}
            for key, value in sorted(by_edge.items())
        },
        "by_odds_bucket": {
            key: {"bets": value["bets"], "profit": round(value["profit"], 4), "roi": round(value["profit"] / value["bets"], 4)}
            for key, value in sorted(by_odds.items())
        },
    }
    return bets, summary


def load_rows(path: str) -> List[dict]:
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"race_id", "race_date", "dog_name", "track", "distance_m", "grade", "trap", "sp_decimal", "finish_pos"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
        return [row for row in reader]


def save_csv(path: str, rows: List[dict]) -> None:
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            handle.write("")
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    raw_rows = load_rows(args.input)
    featured_rows, feature_names = build_features(raw_rows)
    train_rows, test_rows = chronological_split(featured_rows, args)

    if not train_rows or not test_rows:
        raise ValueError("Training/test split produced an empty partition. Check your dates or train ratio.")

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
    bets, summary = backtest(test_rows, normalized_probs, args)

    model_info = {
        "feature_names": feature_names,
        "weights": {name: round(weight, 6) for name, weight in zip(feature_names, weights)},
        "bias": round(bias, 6),
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "train_dates": [min(row["race_date"] for row in train_rows), max(row["race_date"] for row in train_rows)],
        "test_dates": [min(row["race_date"] for row in test_rows), max(row["race_date"] for row in test_rows)],
        "params": {
            "min_edge": args.min_edge,
            "min_odds": args.min_odds,
            "max_odds": args.max_odds,
            "min_prob_gap": args.min_prob_gap,
            "stake": args.stake,
            "learning_rate": args.learning_rate,
            "epochs": args.epochs,
            "l2": args.l2,
        },
    }

    save_csv(os.path.join(args.output_dir, "bets.csv"), bets)
    with open(os.path.join(args.output_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump({"model": model_info, "results": summary}, handle, indent=2)

    print(json.dumps({"model": model_info, "results": summary}, indent=2))


if __name__ == "__main__":
    main()
