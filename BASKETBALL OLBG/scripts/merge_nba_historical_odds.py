from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"


def load_rows(patterns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for pattern in patterns:
        for match in sorted(glob.glob(pattern)):
            path = Path(match)
            if path in seen_paths or path.name.endswith("_manifest.json"):
                continue
            seen_paths.add(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                rows.extend(item for item in payload if isinstance(item, dict))
    return rows


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        match_link = str(row.get("match_link") or "")
        if not match_link:
            continue
        current = best_by_key.get(match_link)
        current_market_len = len((current or {}).get("home_away_market") or [])
        candidate_market_len = len(row.get("home_away_market") or [])
        if current is None or candidate_market_len >= current_market_len:
            best_by_key[match_link] = row
    merged = list(best_by_key.values())
    merged.sort(key=lambda item: str(item.get("match_date") or ""))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge and dedupe cached NBA historical odds snapshots.")
    parser.add_argument(
        "--glob",
        dest="globs",
        action="append",
        help="Input glob. Repeatable. Defaults to data/raw/oddsportal_nba_*.json",
    )
    parser.add_argument(
        "--output-json",
        default=str(RAW_DIR / "oddsportal_nba_merged.json"),
        help="Path for merged JSON output.",
    )
    parser.add_argument(
        "--output-summary",
        default=str(RAW_DIR / "oddsportal_nba_merged_summary.json"),
        help="Path for merged summary output.",
    )
    args = parser.parse_args()

    patterns = args.globs or [str(RAW_DIR / "oddsportal_nba_*.json")]
    rows = load_rows(patterns)
    merged = dedupe_rows(rows)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    summary = {
        "input_patterns": patterns,
        "input_rows": len(rows),
        "merged_rows": len(merged),
        "date_range": {
            "start": merged[0]["match_date"] if merged else None,
            "end": merged[-1]["match_date"] if merged else None,
        },
    }
    output_summary = Path(args.output_summary)
    output_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Merged JSON: {output_json}")
    print(f"Summary: {output_summary}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
