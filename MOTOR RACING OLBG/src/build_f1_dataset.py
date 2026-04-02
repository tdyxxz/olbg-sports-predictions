import argparse
import csv
from collections import defaultdict
from pathlib import Path


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


def load_csv(path):
    with open(path, "r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sort_results(rows):
    rows.sort(key=lambda row: (parse_int(row["season"]), parse_int(row["round"]), row["driver"]))
    return rows


def aggregate_odds(rows, preferred_bookmaker=None):
    grouped = defaultdict(list)
    for row in rows:
        if preferred_bookmaker and row["bookmaker"].strip().lower() != preferred_bookmaker.strip().lower():
            continue
        key = (row["event_date"], row["race_name"], row["driver"], row["market"])
        grouped[key].append(parse_float(row["decimal_odds"]))

    aggregated = {}
    for key, prices in grouped.items():
        if prices:
            aggregated[key] = sum(prices) / len(prices)
    return aggregated


def mean(values, default=0.0):
    return sum(values) / len(values) if values else default


def rate(values, predicate):
    if not values:
        return 0.0
    hits = sum(1 for value in values if predicate(value))
    return hits / len(values)


def build_dataset(results_rows, odds_lookup):
    history_by_driver = defaultdict(list)
    history_by_team = defaultdict(list)
    history_by_driver_circuit = defaultdict(list)
    dataset_rows = []

    grouped_races = defaultdict(list)
    for row in results_rows:
        race_key = (row["season"], row["round"], row["race_date"], row["race_name"])
        grouped_races[race_key].append(row)

    for race_key in sorted(grouped_races.keys(), key=lambda key: (parse_int(key[0]), parse_int(key[1]))):
        race_rows = grouped_races[race_key]
        prior_team_strength = {}
        for row in race_rows:
            team = row["team"]
            team_history = history_by_team[team]
            prior_team_strength[team] = mean(
                [parse_float(item["team_points_in_race"]) for item in team_history[-5:]],
                default=0.0,
            )

        ranked_teams = sorted(
            [(team_name, strength) for team_name, strength in prior_team_strength.items() if strength > 0],
            key=lambda item: item[1],
            reverse=True,
        )
        prior_constructor_rank = {
            team_name: index + 1 for index, (team_name, _) in enumerate(ranked_teams)
        }

        for row in race_rows:
            driver = row["driver"]
            team = row["team"]
            circuit = row["circuit"]

            driver_history = history_by_driver[driver]
            team_history = history_by_team[team]
            circuit_history = history_by_driver_circuit[(driver, circuit)]

            same_race_rows = grouped_races[race_key]
            teammate_rows = [candidate for candidate in same_race_rows if candidate["team"] == team and candidate["driver"] != driver]
            teammate = teammate_rows[0] if teammate_rows else None
            grid_position = parse_int(row["grid_position"])
            recent_dnf_rate = rate(driver_history[-5:], lambda item: parse_int(item["actual_dnf"]) == 1)
            team_recent_points_avg = mean(
                [parse_float(item["team_points_in_race"]) for item in team_history[-5:]],
                default=0.0,
            )
            team_reliability_rate = 1.0 - rate(
                team_history[-10:],
                lambda item: parse_int(item["actual_dnf"]) == 1,
            )
            clean_air_score = max(0.0, 1.0 - ((grid_position - 1) / 19.0)) if grid_position else 0.0
            free_stop_score = clean_air_score * max(0.0, team_reliability_rate - recent_dnf_rate)

            feature_row = {
                "season": row["season"],
                "round": row["round"],
                "race_date": row["race_date"],
                "race_name": row["race_name"],
                "circuit": circuit,
                "driver": driver,
                "team": team,
                "grid_position": grid_position,
                "recent_avg_finish": mean([parse_float(item["finish_position"]) for item in driver_history[-5:] if parse_int(item["finish_position"]) > 0], default=12.0),
                "recent_avg_grid": mean([parse_float(item["grid_position"]) for item in driver_history[-5:] if parse_int(item["grid_position"]) > 0], default=12.0),
                "recent_podium_rate": rate(driver_history[-5:], lambda item: parse_int(item["actual_podium_finish"]) == 1),
                "recent_points_rate": rate(driver_history[-5:], lambda item: parse_int(item["actual_points_finish"]) == 1),
                "recent_fastest_lap_rate": rate(driver_history[-8:], lambda item: parse_int(item["actual_fastest_lap"]) == 1),
                "recent_dnf_rate": recent_dnf_rate,
                "team_recent_points_avg": team_recent_points_avg,
                "team_reliability_rate": team_reliability_rate,
                "driver_track_podium_rate": rate(circuit_history[-3:], lambda item: parse_int(item["actual_podium_finish"]) == 1),
                "driver_track_fastest_lap_rate": rate(circuit_history[-3:], lambda item: parse_int(item["actual_fastest_lap"]) == 1),
                "driver_track_points_rate": rate(circuit_history[-3:], lambda item: parse_int(item["actual_points_finish"]) == 1),
                "teammate_grid_delta": grid_position - parse_int(teammate["grid_position"]) if teammate else 0.0,
                "constructor_rank": prior_constructor_rank.get(team, 10),
                "track_overtake_difficulty": 0.5,
                "track_deg_index": 0.5,
                "track_safety_car_index": 0.5,
                "expected_clean_air_score": clean_air_score,
                "expected_free_stop_score": free_stop_score,
                "weather_wet_flag": 0,
                "odds_podium_finish": odds_lookup.get((row["race_date"], row["race_name"], driver, "podium_finish"), ""),
                "odds_fastest_lap": odds_lookup.get((row["race_date"], row["race_name"], driver, "fastest_lap"), ""),
                "odds_points_finish": odds_lookup.get((row["race_date"], row["race_name"], driver, "points_finish"), ""),
                "actual_podium_finish": parse_int(row["actual_podium_finish"]),
                "actual_fastest_lap": parse_int(row["actual_fastest_lap"]),
                "actual_points_finish": parse_int(row["actual_points_finish"]),
            }

            dataset_rows.append(feature_row)
        team_points_in_race = defaultdict(float)
        for row in race_rows:
            team_points_in_race[row["team"]] += parse_float(row["points"])

        for row in race_rows:
            enriched = dict(row)
            enriched["team_points_in_race"] = team_points_in_race[row["team"]]
            enriched["constructor_rank"] = prior_constructor_rank.get(row["team"], 10)
            history_by_driver[row["driver"]].append(enriched)
            history_by_team[row["team"]].append(enriched)
            history_by_driver_circuit[(row["driver"], row["circuit"])].append(enriched)

    return dataset_rows


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No dataset rows were generated.")
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Build the historical F1 model dataset.")
    parser.add_argument(
        "--results",
        default=str(Path("data") / "raw" / "f1_results.csv"),
        help="Path to normalized F1 results CSV.",
    )
    parser.add_argument(
        "--odds",
        default=str(Path("data") / "raw" / "f1_odds_long.csv"),
        help="Path to normalized long-format odds CSV.",
    )
    parser.add_argument(
        "--output",
        default=str(Path("data") / "historical_f1_driver_markets.csv"),
        help="Output dataset path.",
    )
    parser.add_argument(
        "--bookmaker",
        default="",
        help="Optional bookmaker filter before aggregation.",
    )
    args = parser.parse_args()

    results_rows = sort_results(load_csv(args.results))
    odds_rows = load_csv(args.odds)
    odds_lookup = aggregate_odds(odds_rows, preferred_bookmaker=args.bookmaker or None)
    dataset_rows = build_dataset(results_rows, odds_lookup)
    write_csv(dataset_rows, Path(args.output))
    print(f"Wrote {len(dataset_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
