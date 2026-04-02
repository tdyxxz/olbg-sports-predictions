from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
RAW_DIR = BASE_DIR / "data" / "raw"
DEFAULT_RESULTS_URLS = [
    "https://www.cricket24.com/india/ipl-2025/results/",
    "https://www.cricket24.com/usa/mlc-2025/results/",
    "https://www.cricket24.com/united-kingdom/vitality-blast-2025/results/",
    "https://www.cricket24.com/australia/big-bash-league-2024-2025/results/",
]
FIELD_SEP = "\u00ac"
KEY_SEP = "\u00f7"
SESSION = requests.Session()


def fetch_html(url: str) -> str:
    response = SESSION.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.text


def extract_results_feed(html: str) -> str:
    marker = 'cjs.initialFeeds["summary-results"]'
    start_idx = html.find(marker)
    if start_idx < 0:
        raise ValueError("summary-results feed was not found")
    data_idx = html.find("data: `", start_idx)
    if data_idx < 0:
        raise ValueError("summary-results data block was not found")
    script_end = html.find("</script>", data_idx)
    if script_end < 0:
        raise ValueError("summary-results script end was not found")
    script_payload = html[data_idx + len("data: `") : script_end]
    feed_end = script_payload.rfind("`,")
    if feed_end < 0:
        raise ValueError("summary-results data terminator was not found")
    return script_payload[:feed_end]


def parse_results_feed(feed: str, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for block in feed.split("~AA")[1:]:
        normalized = block.lstrip(KEY_SEP).rstrip("~")
        tokens = normalized.split(FIELD_SEP)
        if not tokens:
            continue
        match_id = tokens[0]
        fields: dict[str, str] = {}
        for token in tokens[1:]:
            if KEY_SEP not in token:
                continue
            key, value = token.split(KEY_SEP, 1)
            fields[key] = value
        home_team = fields.get("AE")
        away_team = fields.get("AF")
        if not home_team or not away_team:
            continue
        winner_flag = fields.get("AS")
        result_text = fields.get("LS", "").strip()
        if winner_flag not in {"1", "2"} and not result_text:
            continue
        records.append(
            {
                "match_id": match_id,
                "match_url": f"https://www.cricket24.com/match/{match_id}/",
                "source_results_url": source_url,
                "date_utc": datetime.fromtimestamp(int(fields["AD"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                "competition": source_url.rstrip("/").split("/")[-2],
                "home_team": home_team,
                "away_team": away_team,
                "winner_flag": winner_flag,
                "result_text": result_text,
            }
        )
    return records


def parse_home_away_odds(page_text: str) -> tuple[float, float] | None:
    patterns = [
        r"HOME/AWAY\s+1X2\s+1\s+2\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)",
        r"ODDS\s+HOME/AWAY\s+1X2\s+1\s+2\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.I)
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def parse_winner(page_text: str, home_team: str, away_team: str, winner_flag: str) -> str | None:
    compact_text = re.sub(r"\s+", " ", page_text)
    for team in (home_team, away_team):
        pattern = re.escape(team) + r"\s+won by"
        if re.search(pattern, compact_text, flags=re.I):
            return team
    if "No result" in compact_text or "Match abandoned" in compact_text:
        return None
    if winner_flag == "1":
        return home_team
    if winner_flag == "2":
        return away_team
    return None


def enrich_matches(records: list[dict[str, Any]], target_size: int, wait_ms: int) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        cookie_accepted = False

        for record in records:
            try:
                page.goto(record["match_url"], wait_until="load", timeout=120000)
                if not cookie_accepted and page.locator("#onetrust-accept-btn-handler").count():
                    page.locator("#onetrust-accept-btn-handler").click(force=True)
                    page.wait_for_timeout(1500)
                    cookie_accepted = True
                page.wait_for_timeout(wait_ms)
                page_text = page.locator("body").inner_text()
            except PlaywrightTimeoutError:
                continue

            odds = parse_home_away_odds(page_text)
            if not odds:
                continue
            winner = parse_winner(page_text, record["home_team"], record["away_team"], record["winner_flag"])
            if not winner:
                continue

            enriched.append(
                {
                    **record,
                    "home_decimal_odds": odds[0],
                    "away_decimal_odds": odds[1],
                    "winner": winner,
                }
            )
            if len(enriched) >= target_size:
                break

        browser.close()
    return enriched


def build_summary(rows: list[dict[str, Any]], target_size: int, source_urls: list[str]) -> dict[str, Any]:
    competitions = sorted({row["competition"] for row in rows if row["competition"]})
    return {
        "target_size": target_size,
        "records": len(rows),
        "date_range": {
            "start": min((row["date_utc"] for row in rows), default=None),
            "end": max((row["date_utc"] for row in rows), default=None),
        },
        "competitions": competitions,
        "source_results_urls": source_urls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a small historical cricket sample with results and home/away odds.")
    parser.add_argument("--results-url", dest="results_urls", action="append", help="Repeatable Cricket24 results page.")
    parser.add_argument("--target-size", type=int, default=40, help="Number of completed match rows to collect.")
    parser.add_argument("--wait-ms", type=int, default=1500, help="Pause after each match page load.")
    parser.add_argument("--output-json", default=str(OUTPUT_DIR / "historical_cricket_sample.json"))
    parser.add_argument("--output-summary", default=str(OUTPUT_DIR / "historical_cricket_sample_summary.json"))
    args = parser.parse_args()

    results_urls = args.results_urls or DEFAULT_RESULTS_URLS
    discovered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for url in results_urls:
        feed = extract_results_feed(fetch_html(url))
        for record in parse_results_feed(feed, url):
            match_id = str(record["match_id"])
            if match_id in seen_ids:
                continue
            seen_ids.add(match_id)
            discovered.append(record)

    enriched = enrich_matches(discovered, args.target_size, args.wait_ms)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_json = Path(args.output_json)
    output_summary = Path(args.output_summary)
    output_json.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    summary = build_summary(enriched, args.target_size, results_urls)
    output_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"JSON: {output_json}")
    print(f"Summary: {output_summary}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
