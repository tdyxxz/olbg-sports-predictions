import argparse
import asyncio
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

EDGE_EXECUTABLE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"
)
BASE_URL = "https://www.oddsportal.com"

LEAGUE_URLS = {
    "france-top-14": "https://www.oddsportal.com/rugby-union/france/top-14/",
    "england-premiership": "https://www.oddsportal.com/rugby-union/england/premiership-rugby/",
    "united-rugby-championship": "https://www.oddsportal.com/rugby-union/world/united-rugby-championship/",
    "super-rugby": "https://www.oddsportal.com/rugby-union/world/super-rugby/",
}


@dataclass
class MatchRecord:
    match_date: str
    competition: str
    season: str
    home_team: str
    away_team: str
    event_url: str
    home_score: int
    away_score: int
    home_moneyline_decimal: float | None
    away_moneyline_decimal: float | None
    handicap_team: str | None
    handicap_line: float | None
    handicap_odds_decimal: float | None
    total_line: float | None
    over_odds_decimal: float | None
    under_odds_decimal: float | None
    source_bookmaker_home_away: str | None
    source_bookmaker_total: str | None
    source_bookmaker_handicap: str | None


def american_to_decimal(odds_text: str) -> float | None:
    odds_text = odds_text.strip()
    if odds_text in {"-", ""}:
        return None
    if odds_text.startswith("+"):
        return round(1 + (float(odds_text[1:]) / 100.0), 4)
    if odds_text.startswith("-"):
        return round(1 + (100.0 / abs(float(odds_text))), 4)
    try:
        value = float(odds_text)
        return value if value > 1 else None
    except ValueError:
        return None


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_first_odds_pair(lines: Iterable[str]) -> tuple[str | None, float | None, float | None]:
    values = list(lines)
    if not values:
        return None, None, None

    bookmaker = values[0]
    numeric = [line for line in values[1:] if re.fullmatch(r"[+-]\d+|\d+(?:\.\d+)?|-", line)]
    decimals = [american_to_decimal(line) for line in numeric]
    decimals = [value for value in decimals if value is not None]

    if len(decimals) >= 2:
        return bookmaker, decimals[0], decimals[1]

    return bookmaker, None, None


def parse_match_summary(body_text: str) -> tuple[str, str, str, int, int]:
    pattern = re.compile(
        r"(?P<home>[^\n]+)\n+(?P<home_score>\d+)\n+–\n+(?P<away_score>\d+)\n+(?P<away>[^\n]+)\n+"
        r"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\n+"
        r"(?P<date>\d{1,2} [A-Za-z]{3} \d{4})",
        re.MULTILINE,
    )
    match = pattern.search(body_text)
    if not match:
        raise ValueError("Could not parse match summary from event page.")

    date_value = pd.to_datetime(match.group("date"), format="%d %b %Y").strftime("%Y-%m-%d")
    return (
        date_value,
        match.group("home").strip(),
        match.group("away").strip(),
        int(match.group("home_score")),
        int(match.group("away_score")),
    )


async def click_if_present(page, selector: str) -> None:
    try:
        locator = page.locator(selector)
        if await locator.count():
            await locator.first.click(timeout=3_000)
            await page.wait_for_timeout(500)
    except Exception:
        return


async def extract_event_links(page) -> list[str]:
    html = await page.content()
    soup = BeautifulSoup(html, "lxml")
    links: set[str] = set()

    for row in soup.find_all(class_=lambda classes: classes and "eventRow" in classes):
        for anchor in row.find_all("a", href=True):
            href = anchor["href"]
            if href.startswith("/rugby-union/") and href.count("/") > 4:
                links.add(f"{BASE_URL}{href}")

    return sorted(links)


async def collect_result_page_links(page, results_url: str, max_pages: int = 12) -> list[str]:
    await page.goto(results_url, wait_until="networkidle", timeout=90_000)
    await click_if_present(page, "#onetrust-accept-btn-handler")
    await page.wait_for_timeout(1_000)

    all_links: set[str] = set(await extract_event_links(page))
    visited_pages = 1
    while visited_pages < max_pages:
        previous_count = len(all_links)
        next_button = page.locator(".pagination a").filter(has_text="Next")
        if await next_button.count() == 0:
            break

        try:
            await next_button.first.click(timeout=10_000)
            await page.wait_for_load_state("networkidle", timeout=90_000)
            await page.wait_for_timeout(1_000)
        except PlaywrightTimeoutError:
            break

        all_links.update(await extract_event_links(page))
        visited_pages += 1
        if len(all_links) == previous_count:
            break

    return sorted(all_links)


async def parse_home_away_market(page) -> tuple[str | None, float | None, float | None]:
    await page.get_by_test_id("bet-types-nav").get_by_text("Home/Away", exact=True).click(timeout=10_000)
    await page.wait_for_timeout(1_200)
    rows = page.locator("div.border-black-borders.flex.h-9")
    for idx in range(await rows.count()):
        row_text = await rows.nth(idx).inner_text()
        lines = clean_lines(row_text)
        bookmaker, home_odds, away_odds = extract_first_odds_pair(lines)
        if home_odds and away_odds:
            return bookmaker, home_odds, away_odds
    return None, None, None


async def parse_totals_market(page) -> tuple[str | None, float | None, float | None, float | None]:
    await page.get_by_test_id("bet-types-nav").get_by_text("Over/Under", exact=True).click(timeout=10_000)
    await page.wait_for_timeout(1_200)
    rows = page.locator("div.border-black-borders.flex.h-9")
    for idx in range(await rows.count()):
        row_text = await rows.nth(idx).inner_text()
        lines = clean_lines(row_text)
        if not lines or not lines[0].startswith("Over/Under"):
            continue
        line_match = re.search(r"([+-]?\d+(?:\.\d+)?)", lines[0])
        if not line_match:
            continue
        numeric = [line for line in lines[1:] if re.fullmatch(r"[+-]\d+|\d+(?:\.\d+)?|-", line)]
        decimals = [american_to_decimal(line) for line in numeric]
        decimals = [value for value in decimals if value is not None]
        if len(decimals) >= 2:
            return "market-average", float(line_match.group(1)), decimals[0], decimals[1]
    return None, None, None, None


async def parse_handicap_market(
    page, home_team: str, away_team: str
) -> tuple[str | None, str | None, float | None, float | None]:
    await page.get_by_test_id("bet-types-nav").get_by_text("Asian Handicap", exact=True).click(timeout=10_000)
    await page.wait_for_timeout(1_200)
    rows = page.locator("div.border-black-borders.flex.h-9")
    for idx in range(await rows.count()):
        row_text = await rows.nth(idx).inner_text()
        lines = clean_lines(row_text)
        if not lines or not lines[0].startswith("Asian Handicap"):
            continue
        line_match = re.search(r"([+-]?\d+(?:\.\d+)?)", lines[0])
        if not line_match:
            continue
        handicap_value = float(line_match.group(1))
        numeric = [line for line in lines[1:] if re.fullmatch(r"[+-]\d+|\d+(?:\.\d+)?|-", line)]
        decimals = [american_to_decimal(line) for line in numeric]
        if len([v for v in decimals if v is not None]) < 2:
            continue
        home_line_odds = decimals[0]
        away_line_odds = decimals[1]
        if home_line_odds is None or away_line_odds is None:
            continue

        if handicap_value < 0:
            return "market-average", "AWAY", abs(handicap_value), away_line_odds
        if handicap_value > 0:
            return "market-average", "HOME", abs(handicap_value), home_line_odds
    return None, None, None, None


async def scrape_event(page, competition: str, season: str, event_url: str) -> MatchRecord | None:
    await page.goto(event_url, wait_until="networkidle", timeout=90_000)
    await click_if_present(page, "#onetrust-accept-btn-handler")
    await page.wait_for_timeout(500)
    body_text = await page.locator("body").inner_text()

    try:
        match_date, home_team, away_team, home_score, away_score = parse_match_summary(body_text)
    except ValueError:
        return None

    source_home_away, home_ml, away_ml = await parse_home_away_market(page)
    source_total, total_line, over_odds, under_odds = await parse_totals_market(page)
    source_handicap, handicap_team, handicap_line, handicap_odds = await parse_handicap_market(
        page, home_team, away_team
    )

    if home_ml is None or away_ml is None:
        return None

    return MatchRecord(
        match_date=match_date,
        competition=competition,
        season=season,
        home_team=home_team,
        away_team=away_team,
        event_url=event_url,
        home_score=home_score,
        away_score=away_score,
        home_moneyline_decimal=home_ml,
        away_moneyline_decimal=away_ml,
        handicap_team=handicap_team,
        handicap_line=handicap_line,
        handicap_odds_decimal=handicap_odds,
        total_line=total_line,
        over_odds_decimal=over_odds,
        under_odds_decimal=under_odds,
        source_bookmaker_home_away=source_home_away,
        source_bookmaker_total=source_total,
        source_bookmaker_handicap=source_handicap,
    )


def save_records(records: list[MatchRecord], output_path: Path) -> None:
    if not records:
        return
    frame = pd.DataFrame(asdict(record) for record in records)
    frame = frame.drop_duplicates(subset=["event_url"]).sort_values(["competition", "season", "match_date", "home_team"])
    frame.to_csv(output_path, index=False)


async def scrape_league_season(
    page, competition: str, season: str, output_path: Path, existing_urls: set[str]
) -> list[MatchRecord]:
    base_url = LEAGUE_URLS[competition].rstrip("/")
    if season == "current":
        results_url = f"{base_url}/results/"
    elif re.fullmatch(r"\d{4}-\d{4}", season):
        results_url = f"{base_url}-{season}/results/"
    elif re.fullmatch(r"\d{4}", season):
        results_url = f"{base_url}-{season}/results/"
    else:
        raise ValueError(f"Unsupported season format: {season}")

    print(f"Collecting links for {competition} {season} from {results_url}")
    links = await collect_result_page_links(page, results_url)
    print(f"Found {len(links)} event links")

    records: list[MatchRecord] = []
    remaining_links = [link for link in links if link not in existing_urls]
    print(f"Need to scrape {len(remaining_links)} new events after resume check")

    for index, event_url in enumerate(remaining_links, start=1):
        try:
            record = await scrape_event(page, competition, season, event_url)
            if record:
                records.append(record)
                existing_urls.add(record.event_url)
                print(
                    f"[{competition} {season}] scraped {index}/{len(remaining_links)}: "
                    f"{record.home_team} vs {record.away_team}"
                )
                save_records(records, output_path)
            else:
                print(f"[{competition} {season}] skipped {index}/{len(remaining_links)}: {event_url}")
        except Exception as exc:
            print(f"[{competition} {season}] failed {index}/{len(remaining_links)}: {event_url} :: {exc}")
            continue

    return records


async def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape historical rugby union odds from OddsPortal.")
    parser.add_argument("--competitions", nargs="+", required=True, choices=sorted(LEAGUE_URLS.keys()))
    parser.add_argument("--seasons", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing_records: list[MatchRecord] = []
    existing_urls: set[str] = set()
    if output_path.exists():
        existing_frame = pd.read_csv(output_path)
        for record_dict in existing_frame.to_dict(orient="records"):
            existing_records.append(MatchRecord(**record_dict))
        existing_urls = {record.event_url for record in existing_records}
        print(f"Resuming from {len(existing_records)} existing rows in {output_path}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=EDGE_EXECUTABLE,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        all_records: list[MatchRecord] = list(existing_records)

        for competition in args.competitions:
            for season in args.seasons:
                new_records = await scrape_league_season(page, competition, season, output_path, existing_urls)
                all_records.extend(new_records)
                save_records(all_records, output_path)

        await browser.close()

    frame = pd.DataFrame(asdict(record) for record in all_records)
    if frame.empty:
        raise SystemExit("No records scraped.")

    frame = frame.drop_duplicates(subset=["event_url"]).sort_values(["competition", "season", "match_date", "home_team"])
    frame.to_csv(output_path, index=False)
    print(f"Saved {len(frame)} rows to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
