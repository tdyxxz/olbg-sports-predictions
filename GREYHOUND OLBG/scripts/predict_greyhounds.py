#!/usr/bin/env python3
"""Generate live greyhound race selections from historical data and an upcoming card."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Tuple

from greyhound_backtest import (
    EPSILON,
    clamp_probability,
    extract_decimal_odds,
    fit_standardizer,
    fraction_places,
    fraction_wins,
    grade_to_strength,
    parse_date,
    predict_probabilities,
    safe_mean,
    train_logistic_regression,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict future greyhound winners from a historical runner file.")
    parser.add_argument("--history", required=True, help="Historical runner CSV used for training.")
    parser.add_argument("--card", required=True, help="Upcoming race card CSV.")
    parser.add_argument("--output-dir", default="outputs/live_predictions", help="Output directory.")
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--min-odds", type=float, default=2.5)
    parser.add_argument("--max-odds", type=float, default=8.0)
    parser.add_argument("--min-prob-gap", type=float, default=0.06)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--l2", type=float, default=0.001)
    return parser.parse_args()


def load_rows(path: str) -> List[dict]:
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def avg_finish(rows: Sequence[dict], default: float = 6.0) -> float:
    finishes = [int(float(row["finish_pos"])) for row in rows if row.get("finish_pos") not in ("", None)]
    finishes = [value for value in finishes if value > 0]
    return safe_mean(finishes, default=default)


def build_live_features(history_rows: List[dict], card_rows: List[dict]) -> Tuple[List[List[float]], List[dict], List[str]]:
    history_rows = sorted(history_rows, key=lambda row: (parse_date(row["race_date"]), row["race_id"], row["dog_name"]))

    dog_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
    dog_track_history: Dict[Tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=10))
    dog_trap_history: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=10))
    dog_distance_history: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=10))
    track_distance_times: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=200))

    last_race_date_by_dog: Dict[str, datetime] = {}
    last_win_date_by_dog: Dict[str, datetime] = {}
    last_distance_by_dog: Dict[str, int] = {}
    last_grade_strength_by_dog: Dict[str, float] = {}

    for row in history_rows:
        dog = row["dog_name"]
        track = row["track"]
        trap = int(float(row.get("trap", 0) or 0))
        distance = int(float(row.get("distance_m", 0) or 0))
        race_date = parse_date(row["race_date"])

        dog_history[dog].append(row)
        dog_track_history[(dog, track)].append(row)
        dog_trap_history[(dog, trap)].append(row)
        dog_distance_history[(dog, distance)].append(row)
        track_distance_times[(track, distance)].append(
            {
                "split_time": float(row.get("split_time", 0) or 0),
                "run_time": float(row.get("run_time", 0) or 0),
            }
        )
        last_race_date_by_dog[dog] = race_date
        last_distance_by_dog[dog] = distance
        last_grade_strength_by_dog[dog] = grade_to_strength(row.get("grade", ""))
        if str(row.get("finish_pos", "")) == "1":
            last_win_date_by_dog[dog] = race_date

    race_sizes = defaultdict(int)
    for row in card_rows:
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

    feature_rows: List[List[float]] = []
    enriched_rows: List[dict] = []

    for row in sorted(card_rows, key=lambda item: (item["race_date"], item["race_id"], item["dog_name"])):
        dog = row["dog_name"]
        track = row["track"]
        trap = int(float(row.get("trap", 0) or 0))
        distance = int(float(row.get("distance_m", 0) or 0))
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
            weighted_recent += weight * (1.0 if str(prior.get("finish_pos", "")) == "1" else 0.0)
        weighted_recent /= sum(weights[: len(recent)]) if recent else 1.0

        days_since_last = 30.0
        if dog in last_race_date_by_dog:
            days_since_last = float((race_date - last_race_date_by_dog[dog]).days)

        days_since_win = 60.0
        if dog in last_win_date_by_dog:
            days_since_win = float((race_date - last_win_date_by_dog[dog]).days)

        grade_strength = grade_to_strength(row.get("grade", ""))
        grade_relief = last_grade_strength_by_dog.get(dog, grade_strength) - grade_strength

        distance_change = float(distance - last_distance_by_dog.get(dog, distance))

        split_time = float(row.get("split_time", 0) or 0)
        run_time = float(row.get("run_time", 0) or 0)
        prior_times = list(track_distance_times[(track, distance)])
        par_split = safe_mean((item["split_time"] for item in prior_times if item["split_time"] > 0), default=0.0)
        par_time = safe_mean((item["run_time"] for item in prior_times if item["run_time"] > 0), default=0.0)
        split_advantage = (par_split - split_time) if split_time > 0 and par_split > 0 else 0.0
        time_advantage = (par_time - run_time) if run_time > 0 and par_time > 0 else 0.0

        feature_vector = [
            market_prob,
            __import__("math").log(sp),
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

        feature_rows.append(feature_vector)
        enriched = dict(row)
        enriched["market_prob"] = market_prob
        enriched["odds"] = sp
        enriched_rows.append(enriched)

    return feature_rows, enriched_rows, feature_names


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


def save_csv(path: str, rows: List[dict]) -> None:
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

    history_rows = load_rows(args.history)
    card_rows = load_rows(args.card)
    if not history_rows or not card_rows:
        raise ValueError("History and card files must both contain rows.")

    from greyhound_backtest import build_features

    featured_history, _ = build_features(history_rows)
    history_features = [row["features"] for row in featured_history]
    history_targets = [row["target"] for row in featured_history]
    standardizer = fit_standardizer(history_features)
    scaled_history = standardizer.transform(history_features)
    weights, bias = train_logistic_regression(
        features=scaled_history,
        targets=history_targets,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2=args.l2,
    )

    card_features, enriched_card_rows, feature_names = build_live_features(history_rows, card_rows)
    scaled_card = standardizer.transform(card_features)
    raw_probs = predict_probabilities(scaled_card, weights, bias)
    normalized_probs = normalize_by_race(enriched_card_rows, raw_probs)

    for row, prob in zip(enriched_card_rows, normalized_probs):
        row["model_prob"] = prob
        row["edge"] = prob - row["market_prob"]

    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in enriched_card_rows:
        grouped[row["race_id"]].append(row)

    selections: List[dict] = []
    for race_id, race_rows in grouped.items():
        ranked = sorted(race_rows, key=lambda row: row["model_prob"], reverse=True)
        top = ranked[0]
        second_prob = ranked[1]["model_prob"] if len(ranked) > 1 else 0.0
        prob_gap = top["model_prob"] - second_prob

        qualifies = (
            top["edge"] >= args.min_edge
            and args.min_odds <= top["odds"] <= args.max_odds
            and prob_gap >= args.min_prob_gap
        )
        confidence = "HIGH" if top["edge"] >= 0.10 and prob_gap >= 0.08 else "MEDIUM" if qualifies else "LOW"
        reason = "BET" if qualifies else "NO SELECTION"
        if not qualifies:
            if top["edge"] < args.min_edge:
                reason = "NO SELECTION: edge below threshold"
            elif not (args.min_odds <= top["odds"] <= args.max_odds):
                reason = "NO SELECTION: odds outside range"
            else:
                reason = "NO SELECTION: probability gap too small"

        selections.append(
            {
                "race_id": race_id,
                "race_date": top["race_date"],
                "race_time": top.get("race_time", ""),
                "track": top["track"],
                "dog_name": top["dog_name"],
                "odds": round(top["odds"], 4),
                "model_prob": round(top["model_prob"], 4),
                "market_prob": round(top["market_prob"], 4),
                "edge": round(top["edge"], 4),
                "prob_gap": round(prob_gap, 4),
                "confidence": confidence,
                "decision": reason,
            }
        )

    selections.sort(key=lambda row: (row["race_date"], row["track"], row["race_time"], row["race_id"]))
    approved = [row for row in selections if row["decision"] == "BET"]

    save_csv(os.path.join(args.output_dir, "all_race_decisions.csv"), selections)
    save_csv(os.path.join(args.output_dir, "approved_bets.csv"), approved)
    with open(os.path.join(args.output_dir, "prediction_summary.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "approved_bets": len(approved),
                "total_races": len(selections),
                "params": {
                    "min_edge": args.min_edge,
                    "min_odds": args.min_odds,
                    "max_odds": args.max_odds,
                    "min_prob_gap": args.min_prob_gap,
                },
                "feature_names": feature_names,
            },
            handle,
            indent=2,
        )

    print(
        json.dumps(
            {
                "approved_bets": len(approved),
                "total_races": len(selections),
                "params": {
                    "min_edge": args.min_edge,
                    "min_odds": args.min_odds,
                    "max_odds": args.max_odds,
                    "min_prob_gap": args.min_prob_gap,
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
