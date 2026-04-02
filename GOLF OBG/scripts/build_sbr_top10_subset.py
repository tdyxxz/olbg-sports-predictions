from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
SBR_GOLF_CATEGORY = "https://www.sportsbookreview.com/picks/golf-picks/"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8", errors="ignore")


def normalize_name(value: str) -> str:
    text = value.lower()
    text = text.replace("&", "and").replace("'", "").replace(".", "").replace("-", " ")
    text = re.sub(r"\b(the|championship|classic|invitational|open|tournament|pres|by|at|in|palm|beaches)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[^a-z0-9]", "", text)


def extract_category_urls() -> List[str]:
    html = fetch_text(SBR_GOLF_CATEGORY)
    urls = re.findall(r"https://www\.sportsbookreview\.com/picks/golf-picks/[^\"'\s<]+", html)
    clean: List[str] = []
    seen: Set[str] = set()
    for url in urls:
        if "#" in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        clean.append(url)
    return clean


def find_title(page_html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(r"<[^>]+>", " ", match.group(1))
    title = title.replace(" - Sportsbook Review", "").replace(" - SBR", "").strip()
    return re.sub(r"\s+", " ", title)


def event_key_from_title(title: str) -> str:
    title = re.sub(r"^\d{4}\s+", "", title)
    title = re.sub(r"\bOdds.*$", "", title, flags=re.IGNORECASE).strip()
    return normalize_name(title)


def american_to_decimal(american: str) -> Optional[float]:
    text = american.strip().upper()
    if not re.fullmatch(r"[+-]\d+", text):
        return None
    value = int(text)
    if value > 0:
        return round((value / 100.0) + 1.0, 4)
    return round((100.0 / abs(value)) + 1.0, 4)


def parse_sbr_top10_table(page_html: str) -> List[Tuple[str, str, float]]:
    idx = page_html.find("Player To Win Top 5 Top 10")
    if idx == -1:
        idx = page_html.find("Top finish odds include ties")
    if idx == -1:
        return []
    segment = page_html[idx : idx + 2500]
    # Embedded article text uses unicode escapes for plus signs and a compact table pattern.
    pattern = re.compile(
        r"([A-Z][A-Za-z\.\-'\s]+?)\\u002B\d+\s+\\u002B\d+\s+(\\u002B\d+)",
        re.DOTALL,
    )
    rows: List[Tuple[str, str, float]] = []
    for player_name, top10_american in pattern.findall(segment):
        player_name = re.sub(r"\s+", " ", player_name).strip()
        american = top10_american.replace("\\u002B", "+")
        decimal = american_to_decimal(american)
        if decimal is None:
            continue
        rows.append((player_name, american, decimal))
    deduped: List[Tuple[str, str, float]] = []
    seen: Set[str] = set()
    for player_name, american, decimal in rows:
        key = normalize_name(player_name)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((player_name, american, decimal))
    return deduped


def load_results(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["event_key"] = normalize_name(row.get("event_name", ""))
        row["player_key"] = normalize_name(row.get("player_name", ""))
    return rows


def build_subset(results_csv: Path, output_csv: Path) -> Dict[str, int]:
    results_rows = load_results(results_csv)
    results_lookup: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = {}
    for row in results_rows:
        if row.get("season") != "2026":
            continue
        event_key = row["event_key"]
        results_lookup.setdefault(("2026", event_key), {})
        results_lookup[("2026", event_key)][row["player_key"]] = row

    matched_rows: List[Dict[str, str]] = []
    matched_events: Set[str] = set()

    for url in extract_category_urls():
        if "golf-picks/" not in url:
            continue
        if not any(token in url for token in ["2026", "odds"]):
            continue
        html = fetch_text(url)
        title = find_title(html)
        event_key = event_key_from_title(title)
        result_players = results_lookup.get(("2026", event_key))
        if not result_players:
            continue
        top10_rows = parse_sbr_top10_table(html)
        if not top10_rows:
            continue
        local_matches = 0
        for player_name, american, decimal in top10_rows:
            result_row = result_players.get(normalize_name(player_name))
            if not result_row:
                continue
            matched_rows.append(
                {
                    "season": "2026",
                    "event_name": result_row.get("event_name", ""),
                    "event_dates": result_row.get("event_dates", ""),
                    "tournament_id": result_row.get("tournament_id", ""),
                    "player_name": result_row.get("player_name", ""),
                    "finish_position": result_row.get("finish_position", ""),
                    "top10_result": result_row.get("top10_result", ""),
                    "top10_odds_american": american,
                    "top10_odds_close": f"{decimal:.4f}",
                    "source": "SportsbookReview",
                    "source_url": url,
                    "article_title": title,
                }
            )
            local_matches += 1
        if local_matches:
            matched_events.add(event_key)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "season",
            "event_name",
            "event_dates",
            "tournament_id",
            "player_name",
            "finish_position",
            "top10_result",
            "top10_odds_american",
            "top10_odds_close",
            "source",
            "source_url",
            "article_title",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(matched_rows)

    return {
        "matched_rows": len(matched_rows),
        "matched_events": len(matched_events),
        "candidate_events_2026": len(results_lookup),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a real-odds 2026 golf top-10 subset from SportsbookReview pages and ESPN results.")
    parser.add_argument("--results", default="data/raw/espn/golf_2023_2026_results.csv")
    parser.add_argument("--output", default="data/raw/sbr/golf_top10_history_sbr_2026_subset.csv")
    args = parser.parse_args()

    summary = build_subset(Path(args.results), Path(args.output))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
