#!/usr/bin/env python3
"""Scrape historical greyhound race results from Timeform archive pages.

The scraper is incremental and resumable:
- one archive page per date
- one race page per result link
- one CSV row per runner

It is intentionally conservative and uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://www.timeform.com"
RESULTS_DAY_URL = BASE_URL + "/greyhound-racing/results/{day}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
DATE_LINK_RE = re.compile(r'href="(?P<href>/greyhound-racing/results/[^"]+/\d{1,4}/\d{4}-\d{2}-\d{2}/\d+)"')

OUTPUT_COLUMNS = [
    "race_id",
    "race_date",
    "race_time",
    "track",
    "race_number",
    "distance_m",
    "grade",
    "race_type",
    "dog_name",
    "dog_url",
    "trap",
    "finish_pos",
    "btn",
    "bend_pos",
    "comments",
    "age_sex",
    "trainer",
    "isp",
    "sp_decimal",
    "run_time",
    "split_time",
    "tfr",
    "forecast_gbp",
    "tricast_gbp",
    "going_allowance",
    "source_url",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Timeform greyhound historical results.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument("--output", required=True, help="CSV path for runner-level history.")
    parser.add_argument("--state-file", default="outputs/timeform_scrape_state.json", help="Checkpoint file.")
    parser.add_argument("--workers", type=int, default=4, help="Race-page workers.")
    parser.add_argument("--delay", type=float, default=0.4, help="Delay in seconds between requests per worker.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--append", action="store_true", help="Append to an existing output CSV if present.")
    parser.add_argument("--ignore-completed-dates", action="store_true", help="Revisit completed dates to retry missing races.")
    return parser.parse_args()


def daterange(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {"completed_dates": [], "completed_races": [], "rows_written": 0, "errors": []}


def save_state(path: str, state: dict) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def get_attr(text: str, pattern: str, default: str = "") -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return strip_tags(match.group(1)) if match else default


class Fetcher:
    def __init__(self, timeout: int, delay: float, retries: int) -> None:
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self._lock = threading.Lock()
        self._last_request = 0.0

    def fetch(self, url: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                with self._lock:
                    elapsed = time.time() - self._last_request
                    if elapsed < self.delay:
                        time.sleep(self.delay - elapsed)
                    self._last_request = time.time()

                request = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    time.sleep(20.0 * (attempt + 1))
                else:
                    time.sleep(min(2.0 * (attempt + 1), 6.0))
            except (URLError, TimeoutError) as exc:
                last_error = exc
                time.sleep(min(2.0 * (attempt + 1), 6.0))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def parse_archive_links(day_html: str, day_str: str) -> List[Tuple[str, str]]:
    seen = set()
    links = []
    for match in DATE_LINK_RE.finditer(day_html):
        href = match.group("href")
        if f"/{day_str}/" not in href:
            continue
        if href not in seen:
            seen.add(href)
            links.append((urljoin(BASE_URL, href), ""))
    return links


def parse_money(value: str) -> float:
    value = strip_tags(value).replace("£", "").replace(",", "").strip()
    try:
        return float(value)
    except ValueError:
        return 0.0


def parse_decimal(value: str) -> float:
    value = strip_tags(value).strip()
    try:
        return float(value)
    except ValueError:
        return 0.0


def safe_int(value: str) -> int:
    value = strip_tags(value).strip()
    try:
        return int(value)
    except ValueError:
        return 0


def parse_title_metadata(title_text: str) -> Dict[str, str]:
    title_text = strip_tags(title_text)
    parts = title_text.split()
    r_index = next((i for i, part in enumerate(parts) if re.fullmatch(r"R\d+", part)), None)
    if r_index is None or len(parts) < r_index + 3:
        return {"track": "", "race_number": "", "grade": "", "distance_m": "", "race_type": ""}

    distance_index = next((i for i, part in enumerate(parts[r_index + 1 :], start=r_index + 1) if re.fullmatch(r"\d+m", part)), None)
    if distance_index is None:
        return {"track": "", "race_number": "", "grade": "", "distance_m": "", "race_type": ""}

    track = " ".join(parts[:r_index]).strip()
    race_number = parts[r_index][1:]
    grade = " ".join(parts[r_index + 1 : distance_index]).strip()
    distance_m = parts[distance_index][:-1]
    race_type = " ".join(parts[distance_index + 1 :]).strip()
    return {
        "track": track,
        "race_number": race_number,
        "grade": grade,
        "distance_m": distance_m,
        "race_type": race_type,
    }


def parse_finish_pos(pos_text: str) -> int:
    cleaned = strip_tags(pos_text).lower()
    cleaned = cleaned.replace("st", "").replace("nd", "").replace("rd", "").replace("th", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_time_and_split(text: str) -> Tuple[float, float]:
    text = strip_tags(text)
    match = re.match(r"([0-9.]+)\s*\(([0-9.]+)\)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    try:
        return float(text), 0.0
    except ValueError:
        return 0.0, 0.0


def fractional_to_decimal(text: str) -> float:
    text = strip_tags(text).lower()
    text = text.replace("jf", "").replace("f", "").strip()
    if not text:
        return 0.0
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            return round(float(left) / float(right) + 1.0, 4)
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


RUNNER_PAIR_RE = re.compile(
    r'<tr class="rrb-runner-details rrb-runner-details-1">(?P<row1>.*?)</tr>\s*'
    r'<tr class="rrb-runner-details rrb-runner-details-2">(?P<row2>.*?)</tr>',
    flags=re.IGNORECASE | re.DOTALL,
)


def parse_race_page(url: str, race_html: str) -> List[dict]:
    active_title = get_attr(race_html, r'class="rph-active-race"[^>]*title="([^"]+)"')
    meta = parse_title_metadata(active_title)
    header = get_attr(race_html, r'<h1 class="w-header">(.+?)</h1>')
    header_clean = strip_tags(header)
    header_match = re.search(r"(\d{1,2}:\d{2})\s+(.+)", header_clean)
    race_time = header_match.group(1) if header_match else ""
    track_from_header = header_match.group(2).strip() if header_match else ""

    date_match = re.search(r"/(\d{4}-\d{2}-\d{2})/", url)
    race_date = date_match.group(1) if date_match else ""
    race_id = url.rstrip("/").split("/")[-1]

    forecast = parse_money(get_attr(race_html, r'<span title="">Forecast:\s*</span>\s*<b title="">([^<]+)</b>'))
    tricast = parse_money(get_attr(race_html, r'<span title="">Tricast:\s*</span>\s*<b title="">([^<]+)</b>'))
    going_allowance = parse_decimal(get_attr(race_html, r'sectorial going allowance for this race">([^<]+)</b>'))
    details_grade = get_attr(race_html, r'The grade/class of this race">Grade:\s*</span>\s*<b[^>]*>([^<]+)</b>')
    details_distance = get_attr(race_html, r'The distance of the race expressed in metres">Distance:\s*</span>\s*<b[^>]*>([^<]+)</b>')

    grade_value = meta["grade"] or details_grade.strip("() ")
    distance_digits = re.sub(r"\D", "", details_distance)
    distance_value = int(meta["distance_m"] or distance_digits or 0)
    race_type_value = meta["race_type"] or "Flat"

    rows = []
    for match in RUNNER_PAIR_RE.finditer(race_html):
        row1 = match.group("row1")
        row2 = match.group("row2")

        dog_name = get_attr(row1, r'<a class="rrb-greyhound[^"]*"[^>]*>(.*?)</a>')
        dog_url = get_attr(row1, r'<a class="rrb-greyhound[^"]*" href="([^"]+)"')
        pos = parse_finish_pos(get_attr(row1, r'rrb-pos[^>]*><span>(.*?)</span>'))
        btn = get_attr(row1, r'al-center" rowspan="2" title="Number of lengths behind the greyhound that finished in front of it">(.*?)</td>')
        trap = get_attr(row1, r'trap-(\d+)\.png')
        age_sex = get_attr(row1, r'rowspan-two" rowspan="2" title="The age and sex of the greyhound">(.*?)</td>')
        bend_pos = get_attr(row1, r'The position of the greyhound at the bends, where applicable">(.*?)</span>')
        comments = get_attr(row1, r'The greyhound&#x27;s official handicap start \(if applicable\), age, gender and run comment in this race">\s*(.*?)\s*</span>')
        isp = get_attr(row1, r'The official starting price of the greyhound in this race">(.*?)</span>')
        tfr = get_attr(row1, r'Timeform&#x27;s rating based on the greyhound&#x27;s overall performance in this race">(.*?)</span>')
        official_time_text = get_attr(row2, r'The official run time of the greyhound in this race \(official sectional\)">(.*?)</span>')
        trainer = get_attr(row2, r'The full name of the greyhound&#x27;s trainer">(.*?)</span>')
        bsp = get_attr(row2, r'The Betfair starting price of the greyhound in this race">(.*?)</span>')
        run_time, split_time = parse_time_and_split(official_time_text)

        rows.append(
            {
                "race_id": race_id,
                "race_date": race_date,
                "race_time": race_time,
                "track": meta["track"] or track_from_header,
                "race_number": meta["race_number"],
                "distance_m": distance_value,
                "grade": grade_value,
                "race_type": race_type_value,
                "dog_name": dog_name,
                "dog_url": urljoin(BASE_URL, dog_url) if dog_url else "",
                "trap": int(trap or 0),
                "finish_pos": pos,
                "btn": strip_tags(btn),
                "bend_pos": bend_pos,
                "comments": comments,
                "age_sex": age_sex,
                "trainer": trainer,
                "isp": strip_tags(isp),
                "sp_decimal": parse_decimal(bsp),
                "run_time": run_time,
                "split_time": split_time,
                "tfr": safe_int(tfr),
                "forecast_gbp": forecast,
                "tricast_gbp": tricast,
                "going_allowance": going_allowance,
                "source_url": url,
            }
        )
    return rows


def load_existing_race_ids(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    race_ids = set()
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            race_id = row.get("race_id")
            if race_id:
                race_ids.add(race_id)
    return race_ids


def append_rows(path: str, rows: Sequence[dict], append: bool) -> int:
    if not rows:
        return 0
    ensure_parent(path)
    file_exists = os.path.exists(path)
    mode = "a" if (append or file_exists) else "w"
    with open(path, mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        if mode == "w" or (mode == "a" and os.path.getsize(path) == 0):
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    args = parse_args()
    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    if end < start:
        raise ValueError("end-date must be on or after start-date")

    state = load_state(args.state_file)
    completed_dates = set(state.get("completed_dates", []))
    completed_races = set(state.get("completed_races", []))
    existing_race_ids = load_existing_race_ids(args.output) if args.append else set()
    completed_races |= existing_race_ids

    fetcher = Fetcher(timeout=args.timeout, delay=args.delay, retries=args.retries)
    total_rows = 0
    total_races = 0

    for day in daterange(start, end):
        day_str = day.isoformat()
        if day_str in completed_dates and not args.ignore_completed_dates:
            continue

        try:
            day_html = fetcher.fetch(RESULTS_DAY_URL.format(day=day_str))
            race_links = parse_archive_links(day_html, day_str)
        except Exception as exc:
            state["errors"].append({"date": day_str, "error": str(exc)})
            save_state(args.state_file, state)
            continue

        new_links = [(url, title) for url, title in race_links if url.rstrip("/").split("/")[-1] not in completed_races]
        scraped_rows: List[dict] = []

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_url = {executor.submit(fetcher.fetch, url): (url, title) for url, title in new_links}
            for future in as_completed(future_to_url):
                url, title = future_to_url[future]
                race_id = url.rstrip("/").split("/")[-1]
                try:
                    race_html = future.result()
                    rows = parse_race_page(url, race_html)
                    if rows:
                        scraped_rows.extend(rows)
                        completed_races.add(race_id)
                        total_races += 1
                except Exception as exc:
                    state["errors"].append({"race_url": url, "title": title, "error": str(exc)})

        total_rows += append_rows(args.output, scraped_rows, append=True)
        completed_dates.add(day_str)
        state["completed_dates"] = sorted(completed_dates)
        state["completed_races"] = sorted(completed_races)
        state["rows_written"] = state.get("rows_written", 0) + len(scraped_rows)
        state["last_completed_date"] = day_str
        save_state(args.state_file, state)
        print(f"{day_str}: races={len(new_links)} rows={len(scraped_rows)} total_rows={total_rows}")

    print(
        json.dumps(
            {
                "output": args.output,
                "state_file": args.state_file,
                "rows_written_this_run": total_rows,
                "races_scraped_this_run": total_races,
                "completed_dates": len(completed_dates),
                "completed_races": len(completed_races),
                "errors": len(state.get("errors", [])),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
