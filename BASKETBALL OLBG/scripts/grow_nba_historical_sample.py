from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
SCRIPTS_DIR = BASE_DIR / "scripts"


def run_step(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def snapshot_path(season: str, pages: int) -> Path:
    return RAW_DIR / f"oddsportal_nba_{season.replace('-', '_')}_pages_{pages:03d}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Grow a cached NBA historical sample with deduped snapshots.")
    parser.add_argument("--season", required=True, help="Season in OddsHarvester format, e.g. 2025-2026.")
    parser.add_argument("--target-pages", type=int, required=True, help="New max-pages value to fetch.")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--full-scrape", action="store_true")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_path = snapshot_path(args.season, args.target_pages)
    fetch_args = [
        str(SCRIPTS_DIR / "fetch_historical_nba_odds.py"),
        "--season",
        args.season,
        "--max-pages",
        str(args.target_pages),
        "--output",
        str(output_path.with_suffix("")),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--request-delay",
        str(args.request_delay),
        "--concurrency",
        str(args.concurrency),
    ]
    if args.full_scrape:
        fetch_args.append("--full-scrape")

    fetch_proc = run_step(fetch_args)
    print(f"[fetch] returncode={fetch_proc.returncode}")
    if fetch_proc.stdout.strip():
        print(fetch_proc.stdout.strip())
    if fetch_proc.stderr.strip():
        print(fetch_proc.stderr.strip())
    if fetch_proc.returncode != 0:
        raise SystemExit(fetch_proc.returncode)

    merged_path = RAW_DIR / f"oddsportal_nba_{args.season.replace('-', '_')}_merged.json"
    summary_path = RAW_DIR / f"oddsportal_nba_{args.season.replace('-', '_')}_merged_summary.json"
    merge_proc = run_step(
        [
            str(SCRIPTS_DIR / "merge_nba_historical_odds.py"),
            "--glob",
            str(RAW_DIR / f"oddsportal_nba_{args.season.replace('-', '_')}*.json"),
            "--output-json",
            str(merged_path),
            "--output-summary",
            str(summary_path),
        ]
    )
    print(f"[merge] returncode={merge_proc.returncode}")
    if merge_proc.stdout.strip():
        print(merge_proc.stdout.strip())
    if merge_proc.stderr.strip():
        print(merge_proc.stderr.strip())
    if merge_proc.returncode != 0:
        raise SystemExit(merge_proc.returncode)

    state = {
        "season": args.season,
        "latest_target_pages": args.target_pages,
        "latest_snapshot": str(output_path),
        "merged_output": str(merged_path),
        "merged_summary": str(summary_path),
    }
    state_path = RAW_DIR / f"oddsportal_nba_{args.season.replace('-', '_')}_state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"State: {state_path}")


if __name__ == "__main__":
    main()
