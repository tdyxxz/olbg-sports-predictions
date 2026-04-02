import argparse
import csv
import json
from pathlib import Path

from f1_backtest import (
    decimal_to_implied_prob,
    expected_value,
    fit_logistic_regression,
    load_config,
    load_rows,
    predict_probabilities,
    safe_float,
)


CONFIDENCE_RULES = {
    "podium_finish": [
        (0.18, "HIGH"),
        (0.12, "MEDIUM"),
        (0.0, "LOW"),
    ],
    "fastest_lap": [
        (0.16, "HIGH"),
        (0.10, "MEDIUM"),
        (0.0, "LOW"),
    ],
}


def load_upcoming_rows(path):
    with open(path, "r", newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    rows = []
    for row in raw_rows:
        first_value = next(iter(row.values()), "")
        if str(first_value).strip().startswith("#"):
            continue
        row["season"] = int(row["season"])
        row["round"] = int(row["round"])
        rows.append(row)
    rows.sort(key=lambda row: row["driver"])
    return rows


def validate_post_qualifying_rows(rows):
    if not rows:
        raise ValueError("Upcoming race file is empty.")

    missing_grid = [
        row["driver"]
        for row in rows
        if safe_float(row.get("grid_position", 0.0)) <= 0
    ]
    if missing_grid:
        joined = ", ".join(missing_grid[:10])
        raise ValueError(
            "Post-qualifying workflow requires final starting grid positions for all rows. "
            f"Missing or invalid grid_position for: {joined}"
        )


def choose_confidence(market_name, edge):
    for threshold, label in CONFIDENCE_RULES[market_name]:
        if edge >= threshold:
            return label
    return "LOW"


def build_rationale(row, market_name):
    if market_name == "podium_finish":
        return (
            f"Starts P{int(safe_float(row['grid_position']))} with recent podium rate "
            f"{safe_float(row['recent_podium_rate']):.0%} and strong team reliability."
        )
    return (
        f"Fastest-lap angle supported by clean-air score {safe_float(row['expected_clean_air_score']):.2f} "
        f"and free-stop score {safe_float(row['expected_free_stop_score']):.2f}."
    )


def score_market(training_rows, upcoming_rows, market_name, market_config, iterations):
    features = market_config["features"]
    weights, stats = fit_logistic_regression(
        training_rows,
        features,
        market_config["label_column"],
        iterations=iterations,
    )
    probabilities = predict_probabilities(upcoming_rows, weights, features, stats)
    odds_column = market_config["odds_column"]
    min_edge = safe_float(market_config["min_edge"])
    min_odds = safe_float(market_config["min_odds"])
    max_bets_per_race = int(market_config["max_bets_per_race"])

    candidates = []
    for row, probability in zip(upcoming_rows, probabilities):
        odds = safe_float(row.get(odds_column, 0.0))
        if odds < min_odds:
            continue
        implied_prob = decimal_to_implied_prob(odds)
        if implied_prob is None:
            continue
        edge = float(probability) - implied_prob
        ev = expected_value(float(probability), odds)
        if edge >= min_edge and ev is not None and ev > 0:
            candidates.append(
                {
                    "race_name": row["race_name"],
                    "circuit": row["circuit"],
                    "driver": row["driver"],
                    "team": row["team"],
                    "market": market_name,
                    "odds": odds,
                    "model_probability": float(probability),
                    "market_probability": implied_prob,
                    "edge": edge,
                    "expected_value": ev,
                    "confidence": choose_confidence(market_name, edge),
                    "grid_position": int(safe_float(row["grid_position"])),
                    "rationale": build_rationale(row, market_name),
                }
            )

    candidates.sort(key=lambda item: (item["edge"], item["expected_value"]), reverse=True)
    return candidates[:max_bets_per_race]


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "race_name",
        "circuit",
        "driver",
        "team",
        "market",
        "odds",
        "model_probability",
        "market_probability",
        "edge",
        "expected_value",
        "confidence",
        "grid_position",
        "rationale",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)


def format_market_block(label, market_name, selections):
    lines = [f"{label}:"]
    market_rows = [row for row in selections if row["market"] == market_name]
    if not market_rows:
        lines.append("- NO SELECTION")
        return "\n".join(lines)

    for row in market_rows:
        lines.append(
            f"- {row['driver']} | Model {row['model_probability']:.1%} | "
            f"Market {row['market_probability']:.1%} | Edge +{row['edge']:.1%} | "
            f"Confidence {row['confidence']}"
        )
        lines.append(f"  {row['rationale']}")
    return "\n".join(lines)


def build_markdown_report(upcoming_rows, selections):
    if upcoming_rows:
        race_name = upcoming_rows[0]["race_name"]
        circuit = upcoming_rows[0]["circuit"]
    else:
        race_name = "Unknown Race"
        circuit = "Unknown Circuit"

    blocks = [
        f"Race: {race_name}",
        f"Circuit: {circuit}",
        "Timing window: Post-qualifying only",
        "",
        format_market_block("Podium Finish", "podium_finish", selections),
        "",
        format_market_block("Fastest Lap", "fastest_lap", selections),
        "",
        "Weekend exposure note:",
        f"- Total recommended bets: {len(selections)}",
        "- Main risk factor: price volatility and small-sample market behavior",
        "- Data timing rule: final grid and post-qualifying odds only",
    ]
    return "\n".join(blocks).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate a podium and fastest-lap race card.")
    parser.add_argument(
        "--history",
        default=str(Path("data") / "historical_f1_driver_markets_from_guides_2020_2025.csv"),
    )
    parser.add_argument(
        "--upcoming",
        default=str(Path("data") / "incoming" / "upcoming_race_template.csv"),
    )
    parser.add_argument(
        "--config",
        default=str(Path("config") / "market_configs_profit_focus.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("outputs")),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=80,
    )
    args = parser.parse_args()

    history_rows = load_rows(args.history)
    upcoming_rows = load_upcoming_rows(args.upcoming)
    validate_post_qualifying_rows(upcoming_rows)
    markets = load_config(args.config)

    selections = []
    for market_name, market_config in markets.items():
        selections.extend(
            score_market(
                training_rows=history_rows,
                upcoming_rows=upcoming_rows,
                market_name=market_name,
                market_config=market_config,
                iterations=args.iterations,
            )
        )

    output_dir = Path(args.output_dir)
    csv_path = output_dir / "race_card_selections.csv"
    json_path = output_dir / "race_card_selections.json"
    markdown_path = output_dir / "race_card_report.md"

    write_csv(selections, csv_path)
    write_json(selections, json_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(build_markdown_report(upcoming_rows, selections), encoding="utf-8")

    print(f"Wrote {len(selections)} selections to {csv_path}")
    print(f"Wrote JSON selections to {json_path}")
    print(f"Wrote markdown report to {markdown_path}")


if __name__ == "__main__":
    main()
