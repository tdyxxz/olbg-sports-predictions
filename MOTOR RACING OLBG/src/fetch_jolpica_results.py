import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://api.jolpi.ca/ergast/f1"


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Codex-F1-Profitability-Model/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_paginated(endpoint):
    offset = 0
    limit = 100
    races = []

    while True:
        url = f"{BASE_URL}/{endpoint}.json?limit={limit}&offset={offset}"
        payload = fetch_json(url)
        mrdata = payload["MRData"]
        race_table = mrdata.get("RaceTable", {})
        page_races = race_table.get("Races", [])
        races.extend(page_races)

        total = int(mrdata.get("total", len(races)))
        offset += limit
        if offset >= total or not page_races:
            break
        time.sleep(0.25)

    return races


def flatten_race_rows(races):
    rows = []
    for race in races:
        season = int(race["season"])
        round_number = int(race["round"])
        race_name = race["raceName"]
        race_date = race["date"]
        circuit = race["Circuit"]["circuitName"]

        qualifying_lookup = {}
        for result in race.get("QualifyingResults", []):
            driver_key = result["Driver"]["driverId"]
            qualifying_lookup[driver_key] = result

        for result in race.get("Results", []):
            driver = result["Driver"]
            constructor = result["Constructor"]
            fastest_lap = result.get("FastestLap", {})
            driver_id = driver["driverId"]
            qualifying = qualifying_lookup.get(driver_id, {})

            position_text = result.get("positionText", "")
            finish_position = parse_int(result.get("position"))
            grid_position = parse_int(result.get("grid"))
            points = parse_float(result.get("points"))
            status = result.get("status", "")

            rows.append(
                {
                    "season": season,
                    "round": round_number,
                    "race_date": race_date,
                    "race_name": race_name,
                    "circuit": circuit,
                    "driver_id": driver_id,
                    "driver": f"{driver['givenName']} {driver['familyName']}",
                    "constructor_id": constructor["constructorId"],
                    "team": constructor["name"],
                    "number": driver.get("permanentNumber", ""),
                    "grid_position": grid_position,
                    "qualifying_position": parse_int(qualifying.get("position")),
                    "qual_q1": qualifying.get("Q1", ""),
                    "qual_q2": qualifying.get("Q2", ""),
                    "qual_q3": qualifying.get("Q3", ""),
                    "finish_position": finish_position,
                    "position_text": position_text,
                    "points": points,
                    "status": status,
                    "laps": parse_int(result.get("laps")),
                    "fastest_lap_rank": parse_int(fastest_lap.get("rank")),
                    "fastest_lap_time": fastest_lap.get("Time", {}).get("time", ""),
                    "fastest_lap_avg_speed": fastest_lap.get("AverageSpeed", {}).get("speed", ""),
                    "actual_podium_finish": 1 if finish_position and finish_position <= 3 else 0,
                    "actual_fastest_lap": 1 if parse_int(fastest_lap.get("rank")) == 1 else 0,
                    "actual_points_finish": 1 if finish_position and finish_position <= 10 else 0,
                    "actual_dnf": 0 if finish_position else 1,
                }
            )
    return rows


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No rows to write.")

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Fetch historical F1 results from Jolpica.")
    parser.add_argument("--start-season", type=int, required=True)
    parser.add_argument("--end-season", type=int, required=True)
    parser.add_argument(
        "--output",
        default=str(Path("data") / "raw" / "f1_results.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    all_races = []
    for season in range(args.start_season, args.end_season + 1):
        print(f"Fetching season {season} results...")
        season_results = fetch_paginated(f"{season}/results")
        print(f"Fetching season {season} qualifying...")
        season_qualifying = fetch_paginated(f"{season}/qualifying")

        qual_by_round = {}
        for race in season_qualifying:
            qual_by_round[(race["season"], race["round"])] = race.get("QualifyingResults", [])

        for race in season_results:
            race["QualifyingResults"] = qual_by_round.get((race["season"], race["round"]), [])
            all_races.append(race)

    rows = flatten_race_rows(all_races)
    write_csv(rows, Path(args.output))
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
