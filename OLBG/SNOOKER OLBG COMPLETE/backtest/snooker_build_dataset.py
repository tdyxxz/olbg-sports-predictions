import argparse
import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DATE_FMT = "%Y-%m-%d"


def load_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_name(value):
    return " ".join((value or "").strip().lower().split())


def parse_date(value):
    return datetime.strptime((value or "").strip()[:10], DATE_FMT)


def as_int(value, default=0):
    text = (value or "").strip()
    return int(text) if text else default


def as_float(value, default=0.0):
    text = (value or "").strip()
    return float(text) if text else default


def first_present(row, keys, default=""):
    for key in keys:
        if key in row and row[key] not in ("", None):
            return row[key]
    return default


def normalize_result_row(row):
    score_a = as_int(row["score_a"])
    score_b = as_int(row["score_b"])
    return {
        "match_id": row["match_id"],
        "event_id": row["event_id"],
        "event_date": row["event_date"],
        "season": row["season"],
        "tournament": row["tournament"],
        "round": row["round"],
        "best_of": as_int(row["best_of"], 0),
        "player_a": row["player_a"],
        "player_b": row["player_b"],
        "player_a_key": normalize_name(row["player_a"]),
        "player_b_key": normalize_name(row["player_b"]),
        "score_a": score_a,
        "score_b": score_b,
        "winner": row["winner"].strip().lower(),
    }


def load_rankings(path):
    if not path:
        return {}
    rows = load_csv(path)
    rankings = {}
    for row in rows:
        season = (row.get("season") or "").strip()
        player_key = normalize_name(first_present(row, ["player_name", "player"]))
        if not season or not player_key:
            continue
        rankings[(season, player_key)] = as_int(first_present(row, ["rank", "position"]))
    return rankings


def load_odds(path):
    rows = load_csv(path)
    odds_index = {}
    for row in rows:
        event_id = (row.get("event_id") or "").strip()
        player_a = normalize_name(row.get("player_a") or "")
        player_b = normalize_name(row.get("player_b") or "")
        if not event_id or not player_a or not player_b:
            continue
        odds_index[(event_id, player_a, player_b)] = row
    return odds_index


def get_odds_row(odds_index, event_id, player_a_key, player_b_key):
    direct = odds_index.get((event_id, player_a_key, player_b_key))
    if direct is not None:
        return direct, False
    swapped = odds_index.get((event_id, player_b_key, player_a_key))
    if swapped is not None:
        return swapped, True
    return None, False


def summarize_last_matches(history, limit):
    recent = history[-limit:]
    wins = sum(1 for item in recent if item["won"])
    frame_diff = sum(item["frame_diff"] for item in recent)
    return wins, frame_diff


def recent_tournament_stats(history, event_id):
    relevant = [item for item in history if item["event_id"] == event_id]
    wins = sum(1 for item in relevant if item["won"])
    frame_diff = sum(item["frame_diff"] for item in relevant)
    return wins, frame_diff


def previous_match_meta(history, current_date):
    if not history:
        return 0.0, 0
    previous = history[-1]
    rest_days = max((current_date - previous["date"]).days, 0)
    return float(rest_days), previous["decider"]


def h2h_stats(matches, player_a_key, player_b_key, current_date):
    cutoff_days = 365 * 3
    wins_a = 0
    wins_b = 0
    for item in matches:
        age = (current_date - item["date"]).days
        if age < 0 or age > cutoff_days:
            continue
        if item["winner_key"] == player_a_key:
            wins_a += 1
        elif item["winner_key"] == player_b_key:
            wins_b += 1
    return wins_a, wins_b


def logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def baseline_model_prob(row):
    rank_a = row["rank_a"]
    rank_b = row["rank_b"]
    rank_term = 0.0
    if rank_a and rank_b:
        rank_term = max(min((rank_b - rank_a) / 32.0, 1.2), -1.2)

    form_term = ((row["last5_wins_a"] - row["last5_wins_b"]) / 5.0) * 0.9
    frame_term = ((row["last5_frame_diff_a"] - row["last5_frame_diff_b"]) / 15.0) * 0.6
    tournament_term = (
        (row["in_tournament_frame_diff_a"] - row["in_tournament_frame_diff_b"]) / 10.0
    ) * 0.35
    rest_term = max(min(row["rest_days_a"] - row["rest_days_b"], 3.0), -3.0) * 0.08
    decider_term = (row["prev_decider_b"] - row["prev_decider_a"]) * 0.22

    total_h2h = row["h2h_3y_wins_a"] + row["h2h_3y_wins_b"]
    if total_h2h:
        h2h_term = ((row["h2h_3y_wins_a"] - row["h2h_3y_wins_b"]) / total_h2h) * 0.35
    else:
        h2h_term = 0.0

    score = rank_term + form_term + frame_term + tournament_term + rest_term + decider_term + h2h_term
    probability = logistic(score)
    return round(min(max(probability, 0.03), 0.97), 4)


def build_dataset(results_rows, odds_index, rankings, require_odds):
    matches = [normalize_result_row(row) for row in results_rows if row.get("winner")]
    matches.sort(key=lambda row: (row["event_date"], row["tournament"], row["round"], row["match_id"]))

    player_history = defaultdict(list)
    h2h_history = defaultdict(list)
    output = []

    for match in matches:
        current_date = parse_date(match["event_date"])
        player_a_key = match["player_a_key"]
        player_b_key = match["player_b_key"]
        history_a = player_history[player_a_key]
        history_b = player_history[player_b_key]

        last5_wins_a, last5_frame_diff_a = summarize_last_matches(history_a, 5)
        last5_wins_b, last5_frame_diff_b = summarize_last_matches(history_b, 5)
        in_tournament_wins_a, in_tournament_frame_diff_a = recent_tournament_stats(history_a, match["event_id"])
        in_tournament_wins_b, in_tournament_frame_diff_b = recent_tournament_stats(history_b, match["event_id"])
        rest_days_a, prev_decider_a = previous_match_meta(history_a, current_date)
        rest_days_b, prev_decider_b = previous_match_meta(history_b, current_date)

        h2h_key = tuple(sorted([player_a_key, player_b_key]))
        h2h_3y_wins_a, h2h_3y_wins_b = h2h_stats(h2h_history[h2h_key], player_a_key, player_b_key, current_date)

        rank_a = rankings.get((match["season"], player_a_key), 0)
        rank_b = rankings.get((match["season"], player_b_key), 0)

        odds_row, swapped = get_odds_row(odds_index, match["event_id"], player_a_key, player_b_key)
        if require_odds and odds_row is None:
            close_odds_a = None
            close_odds_b = None
            price_taken_a = None
            price_taken_b = None
        elif odds_row is None:
            close_odds_a = ""
            close_odds_b = ""
            price_taken_a = ""
            price_taken_b = ""
        else:
            close_odds_a = odds_row["close_odds_b"] if swapped else odds_row["close_odds_a"]
            close_odds_b = odds_row["close_odds_a"] if swapped else odds_row["close_odds_b"]
            price_taken_a = odds_row.get("price_taken_b", "") if swapped else odds_row.get("price_taken_a", "")
            price_taken_b = odds_row.get("price_taken_a", "") if swapped else odds_row.get("price_taken_b", "")

        output_row = {
            "event_id": match["event_id"],
            "event_date": match["event_date"],
            "season": match["season"],
            "tournament": match["tournament"],
            "round": match["round"],
            "best_of": match["best_of"],
            "player_a": match["player_a"],
            "player_b": match["player_b"],
            "rank_a": rank_a,
            "rank_b": rank_b,
            "last5_wins_a": last5_wins_a,
            "last5_wins_b": last5_wins_b,
            "last5_frame_diff_a": last5_frame_diff_a,
            "last5_frame_diff_b": last5_frame_diff_b,
            "in_tournament_wins_a": in_tournament_wins_a,
            "in_tournament_wins_b": in_tournament_wins_b,
            "in_tournament_frame_diff_a": in_tournament_frame_diff_a,
            "in_tournament_frame_diff_b": in_tournament_frame_diff_b,
            "rest_days_a": round(rest_days_a, 2),
            "rest_days_b": round(rest_days_b, 2),
            "prev_decider_a": prev_decider_a,
            "prev_decider_b": prev_decider_b,
            "h2h_3y_wins_a": h2h_3y_wins_a,
            "h2h_3y_wins_b": h2h_3y_wins_b,
            "model_prob_a": 0.0,
            "price_taken_a": price_taken_a,
            "price_taken_b": price_taken_b,
            "close_odds_a": close_odds_a,
            "close_odds_b": close_odds_b,
            "winner": match["winner"],
            "score_a": match["score_a"],
            "score_b": match["score_b"],
            "notes": "",
        }
        output_row["model_prob_a"] = baseline_model_prob(output_row)

        if not require_odds or odds_row is not None:
            output.append(output_row)

        best_of = match["best_of"] or (match["score_a"] + match["score_b"])
        decider_flag = 1 if best_of and (match["score_a"] + match["score_b"] >= best_of - 1) else 0

        if match["winner"] == "player_a":
            winner_key = player_a_key
        else:
            winner_key = player_b_key

        player_history[player_a_key].append(
            {
                "date": current_date,
                "event_id": match["event_id"],
                "won": match["winner"] == "player_a",
                "frame_diff": match["score_a"] - match["score_b"],
                "decider": decider_flag,
            }
        )
        player_history[player_b_key].append(
            {
                "date": current_date,
                "event_id": match["event_id"],
                "won": match["winner"] == "player_b",
                "frame_diff": match["score_b"] - match["score_a"],
                "decider": decider_flag,
            }
        )
        h2h_history[h2h_key].append({"date": current_date, "winner_key": winner_key})

    return output


def main():
    parser = argparse.ArgumentParser(description="Build a snooker value dataset from raw results and odds.")
    parser.add_argument("--results", required=True, help="Normalized snooker results CSV")
    parser.add_argument("--odds", required=True, help="Historical snooker odds CSV")
    parser.add_argument("--rankings", default="", help="Optional rankings CSV")
    parser.add_argument(
        "--allow-missing-odds",
        action="store_true",
        help="Keep rows even if no odds row is found",
    )
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    results_rows = load_csv(Path(args.results))
    odds_index = load_odds(Path(args.odds))
    rankings = load_rankings(Path(args.rankings)) if args.rankings else {}

    output_rows = build_dataset(
        results_rows=results_rows,
        odds_index=odds_index,
        rankings=rankings,
        require_odds=not args.allow_missing_odds,
    )

    fieldnames = [
        "event_id",
        "event_date",
        "season",
        "tournament",
        "round",
        "best_of",
        "player_a",
        "player_b",
        "rank_a",
        "rank_b",
        "last5_wins_a",
        "last5_wins_b",
        "last5_frame_diff_a",
        "last5_frame_diff_b",
        "in_tournament_wins_a",
        "in_tournament_wins_b",
        "in_tournament_frame_diff_a",
        "in_tournament_frame_diff_b",
        "rest_days_a",
        "rest_days_b",
        "prev_decider_a",
        "prev_decider_b",
        "h2h_3y_wins_a",
        "h2h_3y_wins_b",
        "model_prob_a",
        "price_taken_a",
        "price_taken_b",
        "close_odds_a",
        "close_odds_b",
        "winner",
        "score_a",
        "score_b",
        "notes",
    ]
    write_csv(Path(args.output), output_rows, fieldnames)
    print(f"Rows written: {len(output_rows)}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
