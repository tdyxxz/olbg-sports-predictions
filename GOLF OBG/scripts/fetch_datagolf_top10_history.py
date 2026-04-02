from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


BASE_URL = "https://feeds.datagolf.com"


def get_json(url: str) -> object:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_text(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def pick_first(row: Dict[str, object], keys: List[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def extract_rows(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "rows", "odds", "players"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        if all(not isinstance(v, (dict, list)) for v in payload.values()):
            return [payload]
    return []


def request_endpoint(path: str, params: Dict[str, object], api_key: str) -> object:
    query = dict(params)
    query["key"] = api_key
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(query)}"
    return get_json(url)


def get_event_list(api_key: str, tour: str) -> List[Dict[str, object]]:
    payload = request_endpoint("historical-odds/event-list", {"tour": tour, "file_format": "json"}, api_key)
    return extract_rows(payload)


def get_historical_top10(api_key: str, tour: str, year: int, book: str) -> List[Dict[str, object]]:
    payload = request_endpoint(
        "historical-odds/outrights",
        {
            "tour": tour,
            "event_id": "all",
            "year": year,
            "market": "top_10",
            "book": book,
            "odds_format": "decimal",
            "file_format": "json",
        },
        api_key,
    )
    return extract_rows(payload)


def get_prediction_archive(api_key: str, event_id: str, year: int) -> List[Dict[str, object]]:
    payload = request_endpoint(
        "preds/pre-tournament-archive",
        {
            "event_id": event_id,
            "year": year,
            "odds_format": "percent",
            "file_format": "json",
        },
        api_key,
    )
    return extract_rows(payload)


def build_prediction_lookup(rows: Iterable[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    lookup: Dict[str, Dict[str, object]] = {}
    for row in rows:
        name = pick_first(row, ["player_name", "player", "name"])
        if not name:
            continue
        lookup[normalize_text(name)] = row
    return lookup


def event_identity(row: Dict[str, object]) -> Tuple[str, str]:
    event_id = pick_first(row, ["event_id", "dg_id", "tournament_id"])
    year = pick_first(row, ["year", "event_year", "season"])
    return event_id, year


def merge_rows(
    odds_rows: List[Dict[str, object]],
    prediction_cache: Dict[Tuple[str, int], Dict[str, Dict[str, object]]],
) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    for row in odds_rows:
        event_id = pick_first(row, ["event_id", "dg_id", "tournament_id"])
        year = int(safe_float(pick_first(row, ["year", "event_year", "season"]), 0))
        player_name = pick_first(row, ["player_name", "player", "name"])
        pred_row: Dict[str, object] = {}
        if event_id and year:
            pred_lookup = prediction_cache.get((event_id, year), {})
            pred_row = pred_lookup.get(normalize_text(player_name), {})

        merged.append(
            {
                "event_id": event_id,
                "event_name": pick_first(row, ["event_name", "event", "tournament_name"]),
                "tour": pick_first(row, ["tour"], ""),
                "event_date": pick_first(row, ["event_date", "date", "start_date"]),
                "player_name": player_name,
                "book": pick_first(row, ["book", "sportsbook"]),
                "top10_odds_open": safe_float(pick_first(row, ["open_odds", "opening_odds", "odds_open", "open"])),
                "top10_odds_close": safe_float(pick_first(row, ["close_odds", "closing_odds", "odds_close", "close"])),
                "finish_position": pick_first(row, ["finish_position", "finish", "pos"]),
                "top10_result": pick_first(row, ["bet_result", "result", "won", "top10_result"]),
                "field_size": pick_first(row, ["field_size"]),
                "dg_top10_prob": safe_float(
                    pick_first(
                        pred_row,
                        ["top_10", "top10", "top10_prob", "prob_top_10", "pred_top_10", "pred_top10"],
                    )
                ),
                "dg_win_prob": safe_float(pick_first(pred_row, ["win", "win_prob", "pred_win"])),
                "raw_event_year": year,
            }
        )
    return merged


def write_csv(rows: List[Dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical golf top-10 odds from DataGolf and merge with archived model probabilities.")
    parser.add_argument("--api-key", help="DataGolf API key. Falls back to DATAGOLF_API_KEY.")
    parser.add_argument("--tours", default="pga", help="Comma-separated tours, e.g. pga,euro,alt")
    parser.add_argument("--years", default="2025", help="Comma-separated years, e.g. 2023,2024,2025")
    parser.add_argument("--books", default="draftkings,fanduel,pinnacle", help="Comma-separated sportsbooks.")
    parser.add_argument("--outdir", default="data/raw/datagolf", help="Directory for merged CSV outputs.")
    parser.add_argument("--sleep-seconds", type=float, default=0.35, help="Delay between API calls.")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DATAGOLF_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing DataGolf API key. Set DATAGOLF_API_KEY or pass --api-key.")

    outdir = Path(args.outdir)
    tours = [item.strip() for item in args.tours.split(",") if item.strip()]
    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    books = [item.strip() for item in args.books.split(",") if item.strip()]

    for tour in tours:
        event_list_rows = get_event_list(api_key, tour)
        write_csv(event_list_rows, outdir / f"{tour}_event_list.csv")

        prediction_cache: Dict[Tuple[str, int], Dict[str, Dict[str, object]]] = {}
        merged_rows_all: List[Dict[str, object]] = []

        for year in years:
            for book in books:
                odds_rows = get_historical_top10(api_key, tour, year, book)
                for odds_row in odds_rows:
                    event_id = pick_first(odds_row, ["event_id", "dg_id", "tournament_id"])
                    row_year = int(safe_float(pick_first(odds_row, ["year", "event_year", "season"]), year))
                    cache_key = (event_id, row_year)
                    if event_id and cache_key not in prediction_cache:
                        pred_rows = get_prediction_archive(api_key, event_id, row_year)
                        prediction_cache[cache_key] = build_prediction_lookup(pred_rows)
                        time.sleep(args.sleep_seconds)

                merged_rows = merge_rows(odds_rows, prediction_cache)
                for row in merged_rows:
                    row["tour"] = tour
                    row["book"] = book
                merged_rows_all.extend(merged_rows)
                write_csv(merged_rows, outdir / f"{tour}_{year}_{book}_top10_merged.csv")
                time.sleep(args.sleep_seconds)

        if merged_rows_all:
            write_csv(merged_rows_all, outdir / f"{tour}_all_merged_top10.csv")


if __name__ == "__main__":
    main()
