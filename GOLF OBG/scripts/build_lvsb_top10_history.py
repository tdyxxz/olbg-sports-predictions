from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
SITEMAPS = [
    "https://lasvegassportsbetting.com/page-sitemap.xml",
    "https://lasvegassportsbetting.com/page-sitemap2.xml",
    "https://lasvegassportsbetting.com/page-sitemap3.xml",
    "https://lasvegassportsbetting.com/post-sitemap.xml",
    *[f"https://lasvegassportsbetting.com/post-sitemap{i}.xml" for i in range(2, 19)],
]


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8", errors="ignore")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def american_to_decimal(american: str) -> Optional[float]:
    text = american.strip().upper()
    if not text:
        return None
    if text == "EVEN":
        return 2.0
    if not re.fullmatch(r"[+-]?\d+", text):
        return None
    value = int(text)
    if value > 0:
        return round((value / 100.0) + 1.0, 4)
    if value < 0:
        return round((100.0 / abs(value)) + 1.0, 4)
    return None


def normalize_name(value: str) -> str:
    text = strip_tags(value).lower()
    replacements = {
        "&": "and",
        "@": "at",
        "'": "",
        ".": "",
        "-": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\b(the|golf|pga|tour|leaderboard|odds|tournament|championships|finishes|finishing|position|major|open)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[^a-z0-9]", "", text)


def slug_to_event_key(url: str) -> Tuple[str, str]:
    slug = url.rstrip("/").split("/")[-1]
    year_match = re.search(r"(20\d{2})", slug)
    year = year_match.group(1) if year_match else ""
    slug = re.sub(r"20\d{2}", "", slug)
    slug = re.sub(
        r"-(pga-tour|pga|golf|fedex-cup-playoffs|playoffs|tournament|tournamentodds|odds|props|betting|major|specials|top-players|tournament-finishes|finishing-position)+$",
        "",
        slug,
    )
    slug = re.sub(r"-(pga-tour-golf|pga-golf|pga-tour-playoffs-golf|pga-tour-golf-fedex-cup-playoffs|tournament-finishes-odds)-?", "", slug)
    return year, normalize_name(slug)


def parse_sitemap_urls() -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()
    for sitemap in SITEMAPS:
        try:
            content = fetch_text(sitemap)
        except Exception:
            continue
        for match in re.findall(r"https://lasvegassportsbetting\.com/golf/[^<\s]+", content):
            if match in seen:
                continue
            seen.add(match)
            urls.append(match)
    return urls


def is_candidate_archive_url(url: str) -> bool:
    if not re.search(r"/golf/.*20\d{2}", url):
        return False
    excluded_terms = [
        "lpga",
        "dp-world",
        "korn-ferry",
        "champion-tour",
        "champion-tour-golf",
        "liv-golf",
        "asian-tour",
        "ladies-european-tour",
        "solheim-cup",
        "presidents-cup",
        "ryder-cup",
        "tgl-",
        "money-list",
        "specials-odds",
    ]
    return not any(term in url for term in excluded_terms)


def extract_updated_date(page_html: str) -> str:
    match = re.search(r"Updated[:\s]+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?\,?\s+\d{4})", page_html, re.IGNORECASE)
    return strip_tags(match.group(1)) if match else ""


def extract_title(page_html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = strip_tags(match.group(1))
    title = title.replace(" - Las Vegas Sports Betting", "").strip()
    return title


def title_to_event_key(title: str) -> Tuple[str, str]:
    text = title.replace(" - Las Vegas Sports Betting", "").strip()
    year_match = re.search(r"(20\d{2})", text)
    year = year_match.group(1) if year_match else ""
    text = re.sub(r"20\d{2}", "", text)
    return year, normalize_name(text)


def extract_source_book(page_html: str) -> str:
    match = re.search(r"source:\s*([^<]+Sportsbook)", page_html, re.IGNORECASE)
    if match:
        return strip_tags(match.group(1))
    if "Bovada" in page_html:
        return "Bovada Sportsbook"
    return ""


def extract_top10_block(page_html: str) -> str:
    patterns = [
        r"Top 10 Finish</strong><br\s*/?>(.*?)(?:<strong>|</p>)",
        r"Top 10 Finish</b><br\s*/?>(.*?)(?:<strong>|</p>)",
        r"Top 10 Finish<br\s*/?>(.*?)(?:Top 20 Finish|<strong>|</p>)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return ""


def parse_top10_prices(block_html: str) -> List[Tuple[str, str]]:
    prices: List[Tuple[str, str]] = []
    for raw_line in re.split(r"<br\s*/?>", block_html):
        line = strip_tags(raw_line)
        if not line:
            continue
        match = re.match(r"(.+?)\s+([+-]\d+|EVEN)$", line, re.IGNORECASE)
        if not match:
            continue
        player_name = match.group(1).strip(" -")
        odds = match.group(2).upper()
        prices.append((player_name, odds))
    return prices


@dataclass
class ArchivePage:
    url: str
    event_year: str
    event_key: str
    title: str
    updated_date: str
    source_book: str
    rows: List[Dict[str, str]]


def scrape_archive_page(url: str) -> Optional[ArchivePage]:
    html = fetch_text(url)
    block = extract_top10_block(html)
    if not block:
        return None

    prices = parse_top10_prices(block)
    if not prices:
        return None

    event_year, event_key = slug_to_event_key(url)
    rows: List[Dict[str, str]] = []
    for player_name, american_odds in prices:
        decimal_odds = american_to_decimal(american_odds)
        if decimal_odds is None:
            continue
        rows.append(
            {
                "archive_player_name": player_name,
                "archive_player_key": normalize_name(player_name),
                "top10_odds_american": american_odds,
                "top10_odds_close": f"{decimal_odds:.4f}",
            }
        )

    if not rows:
        return None

    return ArchivePage(
        url=url,
        event_year=event_year,
        event_key=event_key,
        title=extract_title(html),
        updated_date=extract_updated_date(html),
        source_book=extract_source_book(html),
        rows=rows,
    )


def load_results(results_csv: Path) -> List[Dict[str, str]]:
    with results_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    for row in rows:
        row["event_year"] = row.get("season", "")
        row["event_key"] = normalize_name(row.get("event_name", ""))
        row["player_key"] = normalize_name(row.get("player_name", ""))
    return rows


def group_results(rows: Iterable[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, Dict[str, str]]]:
    grouped: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = {}
    for row in rows:
        key = (row.get("event_year", ""), row.get("event_key", ""))
        grouped.setdefault(key, {})
        grouped[key][row["player_key"]] = row
    return grouped


def build_lvsb_history(
    results_csv: Path,
    output_csv: Path,
    unmatched_events_csv: Path,
    sleep_seconds: float,
) -> Dict[str, int]:
    results_rows = load_results(results_csv)
    results_lookup = group_results(results_rows)
    target_events = {(row["event_year"], row["event_key"]) for row in results_rows}

    urls = [url for url in parse_sitemap_urls() if is_candidate_archive_url(url)]
    matched_rows: List[Dict[str, str]] = []
    unmatched_events: List[Dict[str, str]] = []
    seen_event_matches: Set[Tuple[str, str]] = set()

    for url in urls:
        event_year, event_key = slug_to_event_key(url)
        if (event_year, event_key) not in target_events:
            continue

        page = scrape_archive_page(url)
        time.sleep(sleep_seconds)
        if page is None:
            unmatched_events.append(
                {
                    "event_year": event_year,
                    "event_key": event_key,
                    "source_url": url,
                    "reason": "no_top10_block",
                }
            )
            continue

        title_year, title_key = title_to_event_key(page.title)
        match_year = page.event_year or title_year
        match_key = title_key or page.event_key

        results_for_event = results_lookup.get((match_year, match_key), {})
        event_match_count = 0
        for archive_row in page.rows:
            result_row = results_for_event.get(archive_row["archive_player_key"])
            if not result_row:
                continue
            event_match_count += 1
            merged = {
                "event_year": match_year,
                "event_name": result_row.get("event_name", ""),
                "event_dates": result_row.get("event_dates", ""),
                "tournament_id": result_row.get("tournament_id", ""),
                "player_name": result_row.get("player_name", ""),
                "finish_position": result_row.get("finish_position", ""),
                "top10_result": result_row.get("top10_result", ""),
                "top10_odds_close": archive_row["top10_odds_close"],
                "top10_odds_american": archive_row["top10_odds_american"],
                "book": page.source_book,
                "updated_date": page.updated_date,
                "archive_title": page.title,
                "archive_url": page.url,
            }
            matched_rows.append(merged)

        if event_match_count > 0:
            seen_event_matches.add((match_year, match_key))
        else:
            unmatched_events.append(
                {
                    "event_year": match_year,
                    "event_key": match_key,
                    "source_url": page.url,
                    "reason": "no_player_matches",
                }
            )

    all_target_events = sorted(target_events)
    matched_targets = seen_event_matches
    for event_year, event_key in all_target_events:
        if (event_year, event_key) in matched_targets:
            continue
        unmatched_events.append(
            {
                "event_year": event_year,
                "event_key": event_key,
                "source_url": "",
                "reason": "no_archive_url_found",
            }
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "event_year",
            "event_name",
            "event_dates",
            "tournament_id",
            "player_name",
            "finish_position",
            "top10_result",
            "top10_odds_close",
            "top10_odds_american",
            "book",
            "updated_date",
            "archive_title",
            "archive_url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(matched_rows)

    unmatched_events_csv.parent.mkdir(parents=True, exist_ok=True)
    with unmatched_events_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["event_year", "event_key", "source_url", "reason"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_events)

    matched_event_count = len({(row["event_year"], normalize_name(row["event_name"])) for row in matched_rows})
    return {
        "matched_rows": len(matched_rows),
        "matched_events": matched_event_count,
        "target_events": len(target_events),
        "unmatched_events": len({(row["event_year"], row["event_key"], row["reason"]) for row in unmatched_events}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build historical golf top-10 odds/results dataset from Las Vegas Sports Betting archive and ESPN results.")
    parser.add_argument("--results", default="data/raw/espn/golf_last_100_tournaments_results.csv", help="ESPN results CSV path.")
    parser.add_argument("--output", default="data/raw/lvsb/golf_top10_history_lvsb.csv", help="Merged output CSV path.")
    parser.add_argument("--unmatched-output", default="data/raw/lvsb/golf_top10_history_lvsb_unmatched.csv", help="Unmatched event report path.")
    parser.add_argument("--sleep-seconds", type=float, default=0.15, help="Delay between archive page requests.")
    args = parser.parse_args()

    summary = build_lvsb_history(
        results_csv=Path(args.results),
        output_csv=Path(args.output),
        unmatched_events_csv=Path(args.unmatched_output),
        sleep_seconds=args.sleep_seconds,
    )
    print(summary)


if __name__ == "__main__":
    main()
