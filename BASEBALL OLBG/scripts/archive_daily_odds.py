from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "data" / "snapshots"
VEGAS_INSIDER_MLB_ODDS = "https://www.vegasinsider.com/mlb/odds/las-vegas/"


def normalize_name(raw: str) -> str:
    raw = raw.strip().lower()
    raw = raw.replace("d-backs", "diamondbacks")
    return raw.split(maxsplit=1)[-1]


def parse_moneyline_rows(table: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    idx = 0
    while idx < len(table) - 1:
        first = table.iloc[idx]
        second = table.iloc[idx + 1]
        idx += 1

        first_label = first.get("Time")
        second_label = second.get("Time")
        if not isinstance(first_label, str) or not isinstance(second_label, str):
            continue
        if first_label == "Matchup" or second_label == "Matchup":
            continue

        consensus_one = str(first.get("Consensus")).strip()
        consensus_two = str(second.get("Consensus")).strip()
        if consensus_one in ("nan", "None") or consensus_two in ("nan", "None"):
            continue

        rows.append(
            {
                "team_1_label": first_label,
                "team_1_name": normalize_name(first_label),
                "team_1_consensus": consensus_one,
                "team_2_label": second_label,
                "team_2_name": normalize_name(second_label),
                "team_2_consensus": consensus_two,
            }
        )
        idx += 1
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive the current public MLB odds board.")
    parser.add_argument("--date", default=str(date.today()), help="Label to use for snapshot filename.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table = pd.read_html(VEGAS_INSIDER_MLB_ODDS)[0]
    rows = parse_moneyline_rows(table)

    stamp = args.date.replace("-", "")
    json_path = OUT_DIR / f"mlb_moneylines_{stamp}.json"
    csv_path = OUT_DIR / f"mlb_moneylines_{stamp}.csv"

    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    print(f"Archived {len(rows)} matchup rows")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
