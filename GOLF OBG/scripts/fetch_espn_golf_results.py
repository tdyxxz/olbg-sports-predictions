from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.request
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional


SCHEDULE_URL = "https://www.espn.com/golf/schedule/_/season/{season}/tour/{tour}"
LEADERBOARD_URL = "https://www.espn.com/golf/leaderboard?tournamentId={tournament_id}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8", errors="ignore")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_tournament_ids(schedule_html: str) -> List[str]:
    ids = re.findall(r"/golf/leaderboard\?tournamentId=(\d+)", schedule_html)
    seen = set()
    ordered: List[str] = []
    for tournament_id in ids:
        if tournament_id in seen:
            continue
        seen.add(tournament_id)
        ordered.append(tournament_id)
    return ordered


def extract_title(page_html: str) -> str:
    og_match = re.search(
        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"|<meta[^>]+content="([^"]+)"[^>]+property="og:title"',
        page_html,
        re.IGNORECASE,
    )
    if og_match:
        title = strip_tags(og_match.group(1) or og_match.group(2))
        if title and title.lower() != "espn_dtc":
            title = (
                title.replace(" Leaderboard - ESPN", "")
                .replace(" Leaderboard – ESPN", "")
                .replace(" Leaderboard â€“ ESPN", "")
                .replace(" - ESPN", "")
                .replace(" – ESPN", "")
                .strip()
            )
            title = re.sub(r"\s+Leaderboard.*$", "", title).strip()
            title = re.sub(r"^\d{4}\s+", "", title).strip()
            return title

    match = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = strip_tags(match.group(1))
    title = (
        title.replace(" Leaderboard - ESPN", "")
        .replace(" Leaderboard – ESPN", "")
        .replace(" Leaderboard â€“ ESPN", "")
        .replace(" - ESPN", "")
        .replace(" – ESPN", "")
        .strip()
    )
    title = re.sub(r"\s+Leaderboard.*$", "", title).strip()
    title = re.sub(r"^\d{4}\s+", "", title).strip()
    return title


def extract_event_dates(page_html: str) -> str:
    month_pattern = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    match = re.search(
        month_pattern + r"\s+\d{1,2}\s*-\s*\d{1,2},\s*\d{4}",
        page_html,
        re.IGNORECASE,
    )
    if match:
        return strip_tags(match.group(0))

    match = re.search(
        month_pattern + r"\s+\d{1,2}\s*-\s*" + month_pattern + r"\s+\d{1,2},\s*\d{4}",
        page_html,
        re.IGNORECASE,
    )
    if match:
        return strip_tags(match.group(0))
    return ""


def extract_rows(page_html: str) -> List[Dict[str, str]]:
    row_pattern = re.compile(
        r'<tr class="PlayerRow__Overview.*?">(.*?)</tr>',
        re.IGNORECASE | re.DOTALL,
    )
    cell_pattern = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
    player_pattern = re.compile(
        r'<a class="AnchorLink leaderboard_player_name"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    rows: List[Dict[str, str]] = []
    for match in row_pattern.finditer(page_html):
        row_html = match.group(1)
        cells = [strip_tags(cell) for cell in cell_pattern.findall(row_html)]
        player_match = player_pattern.search(row_html)
        if not player_match or len(cells) < 10:
            continue

        player_name = strip_tags(player_match.group(1))
        position = cells[1]
        score = cells[3]
        rounds = cells[4:8]
        total = cells[8]
        earnings = cells[9] if len(cells) > 9 else ""
        fedex = cells[10] if len(cells) > 10 else ""

        rows.append(
            {
                "finish_position": position,
                "player_name": player_name,
                "score": score,
                "r1": rounds[0] if len(rounds) > 0 else "",
                "r2": rounds[1] if len(rounds) > 1 else "",
                "r3": rounds[2] if len(rounds) > 2 else "",
                "r4": rounds[3] if len(rounds) > 3 else "",
                "total_strokes": total,
                "earnings": earnings,
                "fedex_pts": fedex,
            }
        )
    return rows


def top10_flag(position: str) -> int:
    text = position.strip().upper()
    if text.startswith("T"):
        text = text[1:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return 0
    return 1 if int(digits) <= 10 else 0


def extract_completed_status(page_html: str) -> bool:
    return "Final" in page_html


def collect_results(
    tours: List[str],
    seasons: List[int],
    limit: int,
    sleep_seconds: float,
) -> List[Dict[str, str]]:
    tournament_ids: List[Dict[str, str]] = []
    for tour in tours:
        for season in seasons:
            schedule_html = fetch_text(SCHEDULE_URL.format(season=season, tour=tour))
            for tournament_id in extract_tournament_ids(schedule_html):
                tournament_ids.append(
                    {
                        "tour": tour,
                        "season": str(season),
                        "tournament_id": tournament_id,
                    }
                )
            time.sleep(sleep_seconds)

    seen = set()
    ordered_ids: List[Dict[str, str]] = []
    for item in tournament_ids:
        key = item["tournament_id"]
        if key in seen:
            continue
        seen.add(key)
        ordered_ids.append(item)

    collected: List[Dict[str, str]] = []
    completed_count = 0
    for item in ordered_ids:
        page_html = fetch_text(LEADERBOARD_URL.format(tournament_id=item["tournament_id"]))
        if not extract_completed_status(page_html):
            continue

        event_name = extract_title(page_html)
        event_dates = extract_event_dates(page_html)
        rows = extract_rows(page_html)
        if not rows:
            continue

        completed_count += 1
        for row in rows:
            row.update(
                {
                    "tour": item["tour"],
                    "season": item["season"],
                    "tournament_id": item["tournament_id"],
                    "event_name": event_name,
                    "event_dates": event_dates,
                    "top10_result": str(top10_flag(row["finish_position"])),
                }
            )
            collected.append(row)

        if completed_count >= limit:
            break
        time.sleep(sleep_seconds)

    return collected


def write_csv(rows: List[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tour",
        "season",
        "tournament_id",
        "event_name",
        "event_dates",
        "finish_position",
        "player_name",
        "score",
        "r1",
        "r2",
        "r3",
        "r4",
        "total_strokes",
        "earnings",
        "fedex_pts",
        "top10_result",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch golf tournament results from ESPN leaderboard pages.")
    parser.add_argument("--tours", default="pga", help="Comma-separated ESPN tour ids, e.g. pga,dp-world")
    parser.add_argument("--seasons", default="2026,2025,2024", help="Comma-separated seasons in descending order.")
    parser.add_argument("--limit", type=int, default=100, help="Number of completed tournaments to collect.")
    parser.add_argument("--sleep-seconds", type=float, default=0.2, help="Delay between requests.")
    parser.add_argument("--output", default="data/raw/espn/golf_last_100_tournaments_results.csv", help="Output CSV path.")
    args = parser.parse_args()

    tours = [item.strip() for item in args.tours.split(",") if item.strip()]
    seasons = [int(item.strip()) for item in args.seasons.split(",") if item.strip()]
    rows = collect_results(tours=tours, seasons=seasons, limit=args.limit, sleep_seconds=args.sleep_seconds)
    write_csv(rows, Path(args.output))
    print(f"Wrote {len(rows)} player rows to {args.output}")


if __name__ == "__main__":
    main()
