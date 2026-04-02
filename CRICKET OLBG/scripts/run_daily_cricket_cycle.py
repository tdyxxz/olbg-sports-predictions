from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / "scripts"
ROOT_SCRIPTS_DIR = BASE_DIR.parents[0] / "scripts"


def run_step(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily cricket board refresh and prediction cycle.")
    parser.add_argument("--date", default=str(date.today()), help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--fast", action="store_true", help="Use fast mode for prediction generation.")
    parser.add_argument("--skip-settlement", action="store_true", help="Skip the settlement refresh step.")
    args = parser.parse_args()

    failures = 0
    olbg_proc = run_step([str(ROOT_SCRIPTS_DIR / "fetch_olbg_event_board.py"), "--sport", "cricket"])
    print(f"[olbg_board] returncode={olbg_proc.returncode}")
    if olbg_proc.stdout.strip():
        print(olbg_proc.stdout.strip())
    if olbg_proc.stderr.strip():
        print(olbg_proc.stderr.strip())
    if olbg_proc.returncode != 0:
        failures += 1

    cmd = [str(SCRIPTS_DIR / "predict_cricket_card.py"), "--date", args.date]
    if args.fast:
        cmd.append("--fast")
    proc = run_step(cmd)
    print(f"[baseline] returncode={proc.returncode}")
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())
    if proc.returncode != 0:
        failures += 1

    if not args.skip_settlement:
        proc = run_step([str(SCRIPTS_DIR / "track_saved_pick_performance.py")])
        print(f"[settlement] returncode={proc.returncode}")
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.stderr.strip():
            print(proc.stderr.strip())
        if proc.returncode != 0:
            failures += 1

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
