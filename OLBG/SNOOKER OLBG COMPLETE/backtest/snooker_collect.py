import argparse
import csv
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.snooker.org/"


def fetch_json(params, requested_by, pause):
    url = f"{API_URL}?{urlencode(params)}"
    request = Request(url, headers={"X-Requested-By": requested_by})
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    if pause:
        time.sleep(pause)
    return json.loads(payload)


def first_present(row, keys, default=""):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def normalize_date(value):
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def normalize_match(event, match_row):
    player_a = first_present(match_row, ["Player1", "PlayerAName", "Player1Name", "Name1"])
    player_b = first_present(match_row, ["Player2", "PlayerBName", "Player2Name", "Name2"])
    score_a = first_present(match_row, ["Score1", "Frames1", "Player1Score"], "")
    score_b = first_present(match_row, ["Score2", "Frames2", "Player2Score"], "")
    round_name = first_present(match_row, ["RoundName", "Round", "RoundText"])
    match_number = first_present(match_row, ["Number", "MatchNo", "Match", "TableNo"])
    best_of = first_present(match_row, ["BestOf", "NumFrames", "Frames"], "")

    if score_a != "" and score_b != "":
        try:
            score_a_int = int(score_a)
            score_b_int = int(score_b)
            if score_a_int > score_b_int:
                winner = "player_a"
            elif score_b_int > score_a_int:
                winner = "player_b"
            else:
                winner = ""
        except ValueError:
            winner = ""
    else:
        winner = ""

    event_id = str(first_present(match_row, ["EventID", "EventId"], first_present(event, ["ID", "EventID"])))
    match_id = first_present(
        match_row,
        ["ID", "MatchID", "MatchId"],
        f"{event_id}_{round_name}_{match_number}_{player_a}_{player_b}",
    )

    return {
        "match_id": str(match_id),
        "event_id": str(event_id),
        "event_date": normalize_date(
            first_present(match_row, ["ScheduledDate", "Date", "SessionDate"], first_present(event, ["StartDate"]))
        ),
        "season": str(first_present(event, ["Season"], "")),
        "tournament": str(first_present(event, ["Name", "Event", "Tournament"])),
        "round": str(round_name),
        "best_of": str(best_of),
        "player_a_id": str(first_present(match_row, ["Player1ID", "PlayerAID", "Player1Id"])),
        "player_a": str(player_a),
        "player_b_id": str(first_present(match_row, ["Player2ID", "PlayerBID", "Player2Id"])),
        "player_b": str(player_b),
        "score_a": str(score_a),
        "score_b": str(score_b),
        "winner": winner,
        "walkover": str(first_present(match_row, ["Walkover", "WO"], "")),
        "status": str(first_present(match_row, ["Status", "MatchStatus"], "")),
    }


def write_csv(path, rows):
    fieldnames = [
        "match_id",
        "event_id",
        "event_date",
        "season",
        "tournament",
        "round",
        "best_of",
        "player_a_id",
        "player_a",
        "player_b_id",
        "player_b",
        "score_a",
        "score_b",
        "winner",
        "walkover",
        "status",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Collect and normalize snooker.org match history.")
    parser.add_argument("--season", required=True, help="Season code used by snooker.org, for example 2024")
    parser.add_argument("--tour", default="main", help="Tour code, default is main")
    parser.add_argument("--requested-by", required=True, help="Approved X-Requested-By value for snooker.org API")
    parser.add_argument("--pause", type=float, default=0.2, help="Pause between requests in seconds")
    parser.add_argument("--output", required=True, help="CSV path for normalized matches")
    args = parser.parse_args()

    try:
        events = fetch_json({"t": 5, "s": args.season, "tr": args.tour}, args.requested_by, args.pause)
    except (HTTPError, URLError) as exc:
        raise SystemExit(f"Failed to fetch season events: {exc}") from exc

    rows = []
    for event in events:
        event_id = first_present(event, ["ID", "EventID"])
        if event_id in ("", None):
            continue
        try:
            matches = fetch_json({"t": 6, "e": event_id}, args.requested_by, args.pause)
        except (HTTPError, URLError) as exc:
            print(f"Skipping event {event_id} due to fetch error: {exc}")
            continue
        for match_row in matches:
            normalized = normalize_match(event, match_row)
            if normalized["player_a"] and normalized["player_b"] and normalized["winner"]:
                rows.append(normalized)

    rows.sort(key=lambda row: (row["event_date"], row["tournament"], row["round"], row["match_id"]))
    write_csv(Path(args.output), rows)
    print(f"Normalized matches written: {len(rows)}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
