from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "outputs"


def parse_match_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC")


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def american_to_decimal(value: float) -> float:
    if value >= 100:
        return 1.0 + (value / 100.0)
    if value <= -100:
        return 1.0 + (100.0 / abs(value))
    return value


def normalized_probabilities(home_decimal: float, away_decimal: float) -> tuple[float, float]:
    raw_home = 1.0 / home_decimal
    raw_away = 1.0 / away_decimal
    total = raw_home + raw_away
    return raw_home / total, raw_away / total


@dataclass
class TeamState:
    games: int = 0
    wins: int = 0
    home_games: int = 0
    home_wins: int = 0
    away_games: int = 0
    away_wins: int = 0
    points_for: int = 0
    points_against: int = 0
    recent_results: deque[int] = field(default_factory=lambda: deque(maxlen=5))
    recent_diffs: deque[int] = field(default_factory=lambda: deque(maxlen=5))

    def overall_win_pct(self) -> float:
        return self.wins / self.games if self.games else 0.5

    def home_win_pct(self) -> float:
        return self.home_wins / self.home_games if self.home_games else 0.5

    def away_win_pct(self) -> float:
        return self.away_wins / self.away_games if self.away_games else 0.5

    def recent_win_pct(self) -> float:
        return sum(self.recent_results) / len(self.recent_results) if self.recent_results else 0.5

    def season_point_diff(self) -> float:
        return (self.points_for - self.points_against) / self.games if self.games else 0.0

    def recent_point_diff(self) -> float:
        return sum(self.recent_diffs) / len(self.recent_diffs) if self.recent_diffs else 0.0


def iter_source_records(patterns: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for pattern in patterns:
        for match in glob.glob(pattern):
            path = Path(match)
            if path in seen_paths or path.name.endswith("_manifest.json"):
                continue
            seen_paths.add(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = [payload]
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        records.append(item)
    return records


def extract_decimal_prices(record: dict[str, Any]) -> tuple[float, float] | None:
    market_rows = record.get("home_away_market") or []
    home_prices: list[float] = []
    away_prices: list[float] = []
    for row in market_rows:
        home_price = as_float(row.get("1"), 0.0)
        away_price = as_float(row.get("2"), 0.0)
        if home_price == 0.0 or away_price == 0.0:
            continue
        if abs(home_price) >= 100 and abs(away_price) >= 100:
            home_price = american_to_decimal(home_price)
            away_price = american_to_decimal(away_price)
        if home_price > 1.0 and away_price > 1.0:
            home_prices.append(home_price)
            away_prices.append(away_price)
    if not home_prices or not away_prices:
        return None
    return sum(home_prices) / len(home_prices), sum(away_prices) / len(away_prices)


def build_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in records:
        prices = extract_decimal_prices(record)
        if not prices:
            continue
        home_score = int(as_float(record.get("home_score"), -1))
        away_score = int(as_float(record.get("away_score"), -1))
        if home_score < 0 or away_score < 0:
            continue
        normalized.append(
            {
                "match_date": parse_match_date(str(record["match_date"])),
                "league_name": str(record.get("league_name") or ""),
                "home_team": str(record["home_team"]),
                "away_team": str(record["away_team"]),
                "home_score": home_score,
                "away_score": away_score,
                "home_decimal_odds": round(prices[0], 4),
                "away_decimal_odds": round(prices[1], 4),
            }
        )
    normalized.sort(key=lambda item: item["match_date"])

    states: dict[str, TeamState] = defaultdict(TeamState)
    rows: list[dict[str, Any]] = []
    for record in normalized:
        home_state = states[record["home_team"]]
        away_state = states[record["away_team"]]

        home_implied, away_implied = normalized_probabilities(
            record["home_decimal_odds"], record["away_decimal_odds"]
        )
        row = {
            "date": record["match_date"].strftime("%Y-%m-%d"),
            "league_name": record["league_name"],
            "home_team": record["home_team"],
            "away_team": record["away_team"],
            "home_decimal_odds": record["home_decimal_odds"],
            "away_decimal_odds": record["away_decimal_odds"],
            "home_implied_prob": round(home_implied, 6),
            "away_implied_prob": round(away_implied, 6),
            "home_overall_win_pct": round(home_state.overall_win_pct(), 6),
            "away_overall_win_pct": round(away_state.overall_win_pct(), 6),
            "home_home_win_pct": round(home_state.home_win_pct(), 6),
            "away_away_win_pct": round(away_state.away_win_pct(), 6),
            "home_recent_win_pct": round(home_state.recent_win_pct(), 6),
            "away_recent_win_pct": round(away_state.recent_win_pct(), 6),
            "home_season_point_diff": round(home_state.season_point_diff(), 6),
            "away_season_point_diff": round(away_state.season_point_diff(), 6),
            "home_recent_point_diff": round(home_state.recent_point_diff(), 6),
            "away_recent_point_diff": round(away_state.recent_point_diff(), 6),
            "home_win": int(record["home_score"] > record["away_score"]),
            "home_score": record["home_score"],
            "away_score": record["away_score"],
        }
        row["overall_win_pct_edge"] = round(row["home_overall_win_pct"] - row["away_overall_win_pct"], 6)
        row["venue_win_pct_edge"] = round(row["home_home_win_pct"] - row["away_away_win_pct"], 6)
        row["recent_win_pct_edge"] = round(row["home_recent_win_pct"] - row["away_recent_win_pct"], 6)
        row["season_point_diff_edge"] = round(
            row["home_season_point_diff"] - row["away_season_point_diff"], 6
        )
        row["recent_point_diff_edge"] = round(
            row["home_recent_point_diff"] - row["away_recent_point_diff"], 6
        )
        rows.append(row)

        home_won = record["home_score"] > record["away_score"]
        away_won = not home_won
        home_diff = record["home_score"] - record["away_score"]
        away_diff = -home_diff

        home_state.games += 1
        home_state.wins += int(home_won)
        home_state.home_games += 1
        home_state.home_wins += int(home_won)
        home_state.points_for += record["home_score"]
        home_state.points_against += record["away_score"]
        home_state.recent_results.append(int(home_won))
        home_state.recent_diffs.append(home_diff)

        away_state.games += 1
        away_state.wins += int(away_won)
        away_state.away_games += 1
        away_state.away_wins += int(away_won)
        away_state.points_for += record["away_score"]
        away_state.points_against += record["home_score"]
        away_state.recent_results.append(int(away_won))
        away_state.recent_diffs.append(away_diff)

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise SystemExit("No usable basketball records were found.")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a rolling NBA moneyline feature dataset from cached odds files.")
    parser.add_argument(
        "--glob",
        dest="globs",
        action="append",
        help="Input glob. Repeatable. Defaults to data/raw/oddsportal_nba_*.json",
    )
    parser.add_argument("--output-csv", default=str(OUTPUT_DIR / "nba_moneyline_feature_dataset.csv"))
    parser.add_argument("--output-summary", default=str(OUTPUT_DIR / "nba_moneyline_feature_dataset_summary.json"))
    args = parser.parse_args()

    patterns = args.globs or [str(RAW_DIR / "oddsportal_nba_*.json")]
    records = iter_source_records(patterns)
    rows = build_rows(records)

    write_csv(Path(args.output_csv), rows)
    summary = {
        "records": len(rows),
        "source_patterns": patterns,
        "date_range": {
            "start": rows[0]["date"] if rows else None,
            "end": rows[-1]["date"] if rows else None,
        },
        "teams": sorted({row["home_team"] for row in rows} | {row["away_team"] for row in rows}),
    }
    summary_path = Path(args.output_summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"CSV: {args.output_csv}")
    print(f"Summary: {args.output_summary}")
    print(json.dumps({"records": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
