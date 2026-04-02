import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path


DATE_FMT = "%Y-%m-%d"

FEATURE_COLUMNS = [
    "rank_gap",
    "last5_wins_diff",
    "last5_frame_diff_gap",
    "in_tournament_wins_diff",
    "in_tournament_frame_diff_gap",
    "rest_days_diff",
    "prev_decider_diff",
    "h2h_3y_wins_diff",
]


def load_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def as_float(value, default=0.0):
    text = (value or "").strip()
    return float(text) if text else default


def as_int(value, default=0):
    text = (value or "").strip()
    return int(text) if text else default


def parse_date(value):
    return datetime.strptime((value or "").strip()[:10], DATE_FMT)


def logistic(x):
    if x >= 0:
        exp_neg = math.exp(-x)
        return 1.0 / (1.0 + exp_neg)
    exp_pos = math.exp(x)
    return exp_pos / (1.0 + exp_pos)


def clip_probability(value):
    return min(max(value, 1e-6), 1.0 - 1e-6)


def build_feature_vector(row):
    rank_a = as_int(row.get("rank_a"))
    rank_b = as_int(row.get("rank_b"))
    if rank_a and rank_b:
        rank_gap = (rank_b - rank_a) / 32.0
    else:
        rank_gap = 0.0

    return {
        "rank_gap": rank_gap,
        "last5_wins_diff": (as_int(row.get("last5_wins_a")) - as_int(row.get("last5_wins_b"))) / 5.0,
        "last5_frame_diff_gap": (
            as_int(row.get("last5_frame_diff_a")) - as_int(row.get("last5_frame_diff_b"))
        ) / 20.0,
        "in_tournament_wins_diff": (
            as_int(row.get("in_tournament_wins_a")) - as_int(row.get("in_tournament_wins_b"))
        ) / 5.0,
        "in_tournament_frame_diff_gap": (
            as_int(row.get("in_tournament_frame_diff_a")) - as_int(row.get("in_tournament_frame_diff_b"))
        ) / 12.0,
        "rest_days_diff": (as_float(row.get("rest_days_a")) - as_float(row.get("rest_days_b"))) / 3.0,
        "prev_decider_diff": as_int(row.get("prev_decider_b")) - as_int(row.get("prev_decider_a")),
        "h2h_3y_wins_diff": (
            as_int(row.get("h2h_3y_wins_a")) - as_int(row.get("h2h_3y_wins_b"))
        ) / 5.0,
    }


def target_from_row(row):
    winner = (row.get("winner") or "").strip().lower()
    if winner == "player_a":
        return 1.0
    if winner == "player_b":
        return 0.0
    raise ValueError(f"Unexpected winner value: {winner}")


def split_rows(rows, train_ratio):
    rows_sorted = sorted(rows, key=lambda row: (row["event_date"], row["event_id"], row["player_a"], row["player_b"]))
    split_index = max(1, min(len(rows_sorted) - 1, int(len(rows_sorted) * train_ratio)))
    return rows_sorted[:split_index], rows_sorted[split_index:]


def fit_standardizer(feature_rows):
    means = {}
    scales = {}
    for column in FEATURE_COLUMNS:
        values = [row[column] for row in feature_rows]
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean) ** 2 for value in values) / len(values) if values else 0.0
        scale = math.sqrt(variance) if variance > 1e-12 else 1.0
        means[column] = mean
        scales[column] = scale
    return means, scales


def standardize_row(feature_row, means, scales):
    return {column: (feature_row[column] - means[column]) / scales[column] for column in FEATURE_COLUMNS}


def dot(weights, feature_row):
    total = weights["bias"]
    for column in FEATURE_COLUMNS:
        total += weights[column] * feature_row[column]
    return total


def initialize_weights():
    weights = {"bias": 0.0}
    for column in FEATURE_COLUMNS:
        weights[column] = 0.0
    return weights


def train_logistic(features, targets, learning_rate, epochs, l2):
    weights = initialize_weights()
    sample_count = len(features)

    for _ in range(epochs):
        gradient = {"bias": 0.0}
        for column in FEATURE_COLUMNS:
            gradient[column] = 0.0

        for feature_row, target in zip(features, targets):
            prediction = logistic(dot(weights, feature_row))
            error = prediction - target
            gradient["bias"] += error
            for column in FEATURE_COLUMNS:
                gradient[column] += error * feature_row[column]

        weights["bias"] -= learning_rate * (gradient["bias"] / sample_count)
        for column in FEATURE_COLUMNS:
            reg_term = l2 * weights[column]
            weights[column] -= learning_rate * ((gradient[column] / sample_count) + reg_term)

    return weights


def predict_probability(weights, feature_row):
    return clip_probability(logistic(dot(weights, feature_row)))


def log_loss(predictions, targets):
    total = 0.0
    for prediction, target in zip(predictions, targets):
        prediction = clip_probability(prediction)
        total += -(target * math.log(prediction) + (1.0 - target) * math.log(1.0 - prediction))
    return total / len(predictions) if predictions else 0.0


def brier_score(predictions, targets):
    total = 0.0
    for prediction, target in zip(predictions, targets):
        total += (prediction - target) ** 2
    return total / len(predictions) if predictions else 0.0


def accuracy(predictions, targets):
    correct = 0
    for prediction, target in zip(predictions, targets):
        predicted_class = 1.0 if prediction >= 0.5 else 0.0
        if predicted_class == target:
            correct += 1
    return correct / len(predictions) if predictions else 0.0


def enrich_rows(rows, means, scales, weights):
    enriched = []
    for row in rows:
        feature_row = build_feature_vector(row)
        standardized = standardize_row(feature_row, means, scales)
        prediction = round(predict_probability(weights, standardized), 4)
        updated = dict(row)
        updated["model_prob_a"] = f"{prediction:.4f}"
        for column in FEATURE_COLUMNS:
            updated[f"feature_{column}"] = f"{feature_row[column]:.6f}"
        enriched.append(updated)
    return enriched


def main():
    parser = argparse.ArgumentParser(description="Train a lightweight logistic model for snooker match probabilities.")
    parser.add_argument("--data", required=True, help="Input snooker value CSV")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of earliest rows used for training")
    parser.add_argument("--learning-rate", type=float, default=0.15, help="Gradient descent learning rate")
    parser.add_argument("--epochs", type=int, default=800, help="Training epochs")
    parser.add_argument("--l2", type=float, default=0.001, help="L2 regularization strength")
    parser.add_argument("--weights-out", default="", help="Optional JSON path for learned weights")
    parser.add_argument("--predictions-out", default="", help="Optional CSV path with updated model_prob_a values")
    args = parser.parse_args()

    rows = load_rows(Path(args.data))
    if len(rows) < 10:
        raise SystemExit("Need at least 10 rows to train and validate the model.")

    for row in rows:
        parse_date(row["event_date"])

    train_rows, test_rows = split_rows(rows, args.train_ratio)
    train_features_raw = [build_feature_vector(row) for row in train_rows]
    test_features_raw = [build_feature_vector(row) for row in test_rows]
    train_targets = [target_from_row(row) for row in train_rows]
    test_targets = [target_from_row(row) for row in test_rows]

    means, scales = fit_standardizer(train_features_raw)
    train_features = [standardize_row(row, means, scales) for row in train_features_raw]
    test_features = [standardize_row(row, means, scales) for row in test_features_raw]

    weights = train_logistic(
        features=train_features,
        targets=train_targets,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2=args.l2,
    )

    train_predictions = [predict_probability(weights, row) for row in train_features]
    test_predictions = [predict_probability(weights, row) for row in test_features]

    print(f"Rows: {len(rows)}")
    print(f"Train rows: {len(train_rows)}")
    print(f"Test rows: {len(test_rows)}")
    print()
    print("Train metrics")
    print(f"  Log loss: {log_loss(train_predictions, train_targets):.4f}")
    print(f"  Brier:    {brier_score(train_predictions, train_targets):.4f}")
    print(f"  Accuracy: {accuracy(train_predictions, train_targets) * 100.0:.2f}%")
    print()
    print("Test metrics")
    print(f"  Log loss: {log_loss(test_predictions, test_targets):.4f}")
    print(f"  Brier:    {brier_score(test_predictions, test_targets):.4f}")
    print(f"  Accuracy: {accuracy(test_predictions, test_targets) * 100.0:.2f}%")
    print()
    print("Weights")
    print(json.dumps(weights, indent=2, sort_keys=True))

    if args.weights_out:
        payload = {
            "feature_columns": FEATURE_COLUMNS,
            "means": means,
            "scales": scales,
            "weights": weights,
            "train_ratio": args.train_ratio,
            "learning_rate": args.learning_rate,
            "epochs": args.epochs,
            "l2": args.l2,
        }
        with open(args.weights_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        print()
        print(f"Weights written to: {args.weights_out}")

    if args.predictions_out:
        enriched_rows = enrich_rows(rows, means, scales, weights)
        fieldnames = list(rows[0].keys()) + [f"feature_{column}" for column in FEATURE_COLUMNS]
        write_rows(Path(args.predictions_out), enriched_rows, fieldnames)
        print(f"Predictions written to: {args.predictions_out}")


if __name__ == "__main__":
    main()
