import argparse
import csv
from pathlib import Path


REQUIRED_COLUMNS = {
    "event_date",
    "race_name",
    "bookmaker",
    "driver",
    "market",
    "outcome",
    "decimal_odds",
}

MARKET_ALIASES = {
    "podium": "podium_finish",
    "podium_finish": "podium_finish",
    "top_3": "podium_finish",
    "fastest_lap": "fastest_lap",
    "fastest lap": "fastest_lap",
    "points_finish": "points_finish",
    "top_10": "points_finish",
    "points": "points_finish",
}


def normalize_market(value):
    key = (value or "").strip().lower()
    if key not in MARKET_ALIASES:
        raise ValueError(f"Unsupported market: {value}")
    return MARKET_ALIASES[key]


def normalize_outcome(value):
    key = (value or "").strip().lower()
    if key not in {"yes", "y", "1", "true"}:
        raise ValueError(f"Only affirmative driver outcome rows are supported, got: {value}")
    return "yes"


def read_rows(input_path):
    with open(input_path, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Missing columns in {input_path}: {sorted(missing)}")
        return list(reader)


def normalize_rows(rows):
    normalized = []
    for row in rows:
        normalized.append(
            {
                "event_date": row["event_date"].strip(),
                "race_name": row["race_name"].strip(),
                "bookmaker": row["bookmaker"].strip(),
                "driver": row["driver"].strip(),
                "market": normalize_market(row["market"]),
                "outcome": normalize_outcome(row["outcome"]),
                "decimal_odds": f"{float(row['decimal_odds']):.6f}",
            }
        )
    return normalized


def write_rows(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_date",
        "race_name",
        "bookmaker",
        "driver",
        "market",
        "outcome",
        "decimal_odds",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Normalize exported F1 odds into canonical long format.")
    parser.add_argument("--input", required=True, help="Input CSV path.")
    parser.add_argument(
        "--output",
        default=str(Path("data") / "raw" / "f1_odds_long.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    rows = read_rows(args.input)
    normalized = normalize_rows(rows)
    write_rows(normalized, Path(args.output))
    print(f"Wrote {len(normalized)} rows to {args.output}")


if __name__ == "__main__":
    main()
