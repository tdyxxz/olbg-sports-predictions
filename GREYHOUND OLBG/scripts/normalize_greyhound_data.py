#!/usr/bin/env python3
"""Normalize messy greyhound historical exports into the backtest schema."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from typing import Dict, List, Optional


REQUIRED_OUTPUT_COLUMNS = [
    "race_id",
    "race_date",
    "dog_name",
    "track",
    "distance_m",
    "grade",
    "trap",
    "sp_decimal",
    "finish_pos",
    "split_time",
    "run_time",
]


ALIASES = {
    "race_id": ["race_id", "race", "event_id", "eventid", "meeting_race_id"],
    "race_date": ["race_date", "date", "event_date", "meeting_date"],
    "race_time": ["race_time", "time_off", "off_time", "scheduled_time", "race_number", "race_no"],
    "dog_name": ["dog_name", "runner", "runner_name", "name", "greyhound"],
    "track": ["track", "venue", "trk", "course"],
    "distance_m": ["distance_m", "distance", "dist", "meters", "metres"],
    "grade": ["grade", "class", "race_grade"],
    "trap": ["trap", "box", "draw", "trap_no"],
    "sp_decimal": ["sp_decimal", "sp", "isp", "starting_price", "industry_sp", "bsp", "betfair_sp"],
    "finish_pos": ["finish_pos", "finish", "fin", "position", "pos"],
    "split_time": ["split_time", "split", "sectional", "tfs_ec", "tfsec"],
    "run_time": ["run_time", "time", "race_time", "tf_time", "tftime"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize raw greyhound results into model-ready CSV.")
    parser.add_argument("--input", required=True, help="Raw CSV input path.")
    parser.add_argument("--output", required=True, help="Normalized CSV output path.")
    return parser.parse_args()


def canonicalize_headers(fieldnames: List[str]) -> Dict[str, str]:
    normalized = {name.lower().strip(): name for name in fieldnames}
    mapping: Dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalized:
                mapping[target] = normalized[alias.lower()]
                break
    return mapping


def normalize_date(value: str) -> str:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def fractional_to_decimal(value: str) -> Optional[float]:
    value = (value or "").strip().lower()
    if not value:
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        try:
            return round(float(left) / float(right) + 1.0, 4)
        except ValueError:
            return None
    try:
        return round(float(value), 4)
    except ValueError:
        return None


def normalize_finish(value: str) -> int:
    value = (value or "").strip().lower()
    if not value:
        return 0
    cleanup = (
        value.replace("st", "")
        .replace("nd", "")
        .replace("rd", "")
        .replace("th", "")
        .replace("=", "")
        .strip()
    )
    try:
        return int(float(cleanup))
    except ValueError:
        return 0


def clean_distance(value: str) -> int:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return int(digits) if digits else 0


def fetch(row: dict, mapping: Dict[str, str], key: str) -> str:
    source = mapping.get(key)
    return row.get(source, "") if source else ""


def build_race_id(row: dict, mapping: Dict[str, str]) -> str:
    existing = fetch(row, mapping, "race_id").strip()
    if existing:
        return existing
    date = normalize_date(fetch(row, mapping, "race_date"))
    track = fetch(row, mapping, "track").strip().replace(" ", "_")
    grade = fetch(row, mapping, "grade").strip().replace(" ", "")
    distance = clean_distance(fetch(row, mapping, "distance_m"))
    race_time = fetch(row, mapping, "race_time").strip().replace(" ", "_").replace(":", "-")
    if race_time:
        return f"{track}_{date}_{race_time}_{grade}_{distance}"
    return f"{track}_{date}_{grade}_{distance}"


def main() -> None:
    args = parse_args()
    with open(args.input, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no headers.")

        mapping = canonicalize_headers(reader.fieldnames)
        missing = [name for name in ("race_date", "dog_name", "track", "distance_m", "grade", "trap", "sp_decimal", "finish_pos") if name not in mapping]
        if missing:
            raise ValueError(f"Could not map required columns: {', '.join(missing)}")

        rows = []
        for raw in reader:
            sp_decimal = fractional_to_decimal(fetch(raw, mapping, "sp_decimal"))
            if sp_decimal is None:
                continue

            normalized = {
                "race_id": build_race_id(raw, mapping),
                "race_date": normalize_date(fetch(raw, mapping, "race_date")),
                "dog_name": fetch(raw, mapping, "dog_name").strip(),
                "track": fetch(raw, mapping, "track").strip(),
                "distance_m": clean_distance(fetch(raw, mapping, "distance_m")),
                "grade": fetch(raw, mapping, "grade").strip(),
                "trap": int(clean_distance(fetch(raw, mapping, "trap")) or 0),
                "sp_decimal": sp_decimal,
                "finish_pos": normalize_finish(fetch(raw, mapping, "finish_pos")),
                "split_time": fractional_to_decimal(fetch(raw, mapping, "split_time")) or 0.0,
                "run_time": fractional_to_decimal(fetch(raw, mapping, "run_time")) or 0.0,
            }
            rows.append(normalized)

    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Normalized {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
