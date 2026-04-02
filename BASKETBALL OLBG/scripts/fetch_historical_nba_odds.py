from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
EXTERNAL_SRC = (
    BASE_DIR.parents[0]
    / "RUGBY UNION OLBG"
    / "_external"
    / "OddsHarvester-master"
    / "src"
)


def normalize_season(season: str) -> str:
    return season.replace("-", "_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache historical NBA odds from OddsHarvester.")
    parser.add_argument("--season", required=True, help="Season in OddsHarvester format, e.g. 2025-2026.")
    parser.add_argument("--output", help="Optional output base path without extension.")
    parser.add_argument("--max-pages", type=int, help="Optional page cap for partial historic pulls.")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="Subprocess timeout.")
    parser.add_argument("--request-delay", type=float, default=0.2, help="Per-request delay passed to scraper.")
    parser.add_argument("--concurrency", type=int, default=2, help="Scraper concurrency.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing cached output.")
    parser.add_argument(
        "--full-scrape",
        action="store_true",
        help="Disable preview-only mode. Slower, but attempts a fuller market scrape.",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_base = (
        Path(args.output)
        if args.output
        else RAW_DIR / f"oddsportal_nba_{normalize_season(args.season)}"
    )
    output_json = output_base.with_suffix(".json")
    manifest_path = output_base.with_name(output_base.name + "_manifest.json")

    if output_json.exists() and not args.force:
        print(f"Using cached file: {output_json}")
        return

    if args.force and output_json.exists():
        output_json.unlink()

    command = [
        sys.executable,
        "-m",
        "oddsharvester",
        "historic",
        "-s",
        "basketball",
        "-l",
        "nba",
        "--season",
        args.season,
        "-m",
        "home_away",
        "--storage",
        "local",
        "-f",
        "json",
        "-o",
        str(output_base),
        "--headless",
        "-c",
        str(max(1, args.concurrency)),
        "--request-delay",
        str(max(0.0, args.request_delay)),
    ]
    if not args.full_scrape:
        command.append("--preview-only")
    if args.max_pages:
        command.extend(["--max-pages", str(args.max_pages)])

    env = dict(os.environ)
    env["PYTHONPATH"] = str(EXTERNAL_SRC)

    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        runtime_seconds = round(time.time() - started, 2)
        manifest = {
            "season": args.season,
            "output_json": str(output_json),
            "runtime_seconds": runtime_seconds,
            "returncode": None,
            "timed_out": True,
            "stdout_tail": (exc.stdout or "")[-4000:],
            "stderr_tail": (exc.stderr or "")[-4000:],
            "command": command,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise SystemExit(
            f"Historical odds fetch timed out after {runtime_seconds}s. See manifest: {manifest_path}"
        ) from exc
    runtime_seconds = round(time.time() - started, 2)

    manifest = {
        "season": args.season,
        "output_json": str(output_json),
        "runtime_seconds": runtime_seconds,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "command": command,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Manifest: {manifest_path}")
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())

    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    if not output_json.exists():
        raise SystemExit(f"Expected output file was not created: {output_json}")

    print(f"Historical odds saved to: {output_json}")


if __name__ == "__main__":
    main()
