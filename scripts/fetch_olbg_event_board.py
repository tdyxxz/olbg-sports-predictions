from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "data" / "cache" / "olbg"

SPORT_CONFIG: dict[str, dict[str, str]] = {
    "baseball": {
        "url": "https://www.olbg.com/betting-tips/Baseball/12",
        "folder": "BASEBALL OLBG",
    },
    "basketball": {
        "url": "https://www.olbg.com/betting-tips/Basketball/4",
        "folder": "BASKETBALL OLBG",
    },
    "cricket": {
        "url": "https://www.olbg.com/betting-tips/Cricket/7",
        "folder": "CRICKET OLBG",
    },
}

SESSION = requests.Session()

BASEBALL_TEAM_ALIASES = {
    "angels": "angels",
    "astros": "astros",
    "athletics": "athletics",
    "a's": "athletics",
    "braves": "braves",
    "atl braves": "braves",
    "blue jays": "blue jays",
    "tor blue jays": "blue jays",
    "brewers": "brewers",
    "cardinals": "cardinals",
    "cubs": "cubs",
    "diamondbacks": "diamondbacks",
    "ari diamondbacks": "diamondbacks",
    "dbacks": "diamondbacks",
    "d-backs": "diamondbacks",
    "dodgers": "dodgers",
    "giants": "giants",
    "sf giants": "giants",
    "guardians": "guardians",
    "mariners": "mariners",
    "marlins": "marlins",
    "mets": "mets",
    "ny mets": "mets",
    "nationals": "nationals",
    "orioles": "orioles",
    "padres": "padres",
    "phillies": "phillies",
    "pirates": "pirates",
    "rangers": "rangers",
    "rays": "rays",
    "reds": "reds",
    "red sox": "red sox",
    "rockies": "rockies",
    "royals": "royals",
    "kc royals": "royals",
    "tigers": "tigers",
    "twins": "twins",
    "min twins": "twins",
    "white sox": "white sox",
    "chi white sox": "white sox",
    "yankees": "yankees",
}

NBA_TEAM_ALIASES = {
    "atl hawks": "hawks",
    "hawks": "hawks",
    "bos celtics": "celtics",
    "celtics": "celtics",
    "bkn nets": "nets",
    "nets": "nets",
    "cha hornets": "hornets",
    "hornets": "hornets",
    "chi bulls": "bulls",
    "bulls": "bulls",
    "cle cavaliers": "cavaliers",
    "cavaliers": "cavaliers",
    "dal mavericks": "mavericks",
    "mavericks": "mavericks",
    "den nuggets": "nuggets",
    "nuggets": "nuggets",
    "det pistons": "pistons",
    "pistons": "pistons",
    "gs warriors": "warriors",
    "golden state warriors": "warriors",
    "warriors": "warriors",
    "hou rockets": "rockets",
    "rockets": "rockets",
    "ind pacers": "pacers",
    "pacers": "pacers",
    "la clippers": "clippers",
    "clippers": "clippers",
    "la lakers": "lakers",
    "lakers": "lakers",
    "mem grizzlies": "grizzlies",
    "grizzlies": "grizzlies",
    "mia heat": "heat",
    "heat": "heat",
    "mil bucks": "bucks",
    "bucks": "bucks",
    "min timberwolves": "timberwolves",
    "timberwolves": "timberwolves",
    "no pelicans": "pelicans",
    "pelicans": "pelicans",
    "ny knicks": "knicks",
    "knicks": "knicks",
    "okc thunder": "thunder",
    "thunder": "thunder",
    "orl magic": "magic",
    "magic": "magic",
    "phi 76ers": "76ers",
    "76ers": "76ers",
    "phx suns": "suns",
    "suns": "suns",
    "por trail blazers": "trail blazers",
    "trail blazers": "trail blazers",
    "sac kings": "kings",
    "kings": "kings",
    "sa spurs": "spurs",
    "spurs": "spurs",
    "tor raptors": "raptors",
    "raptors": "raptors",
    "uta jazz": "jazz",
    "jazz": "jazz",
    "wsh wizards": "wizards",
    "was wizards": "wizards",
    "wizards": "wizards",
}


def cache_is_fresh(path: Path, max_age_minutes: int) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) <= max_age_minutes * 60


def fetch_html(sport: str, url: str, cache_minutes: int) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{sport}.html"
    if cache_is_fresh(cache_path, cache_minutes):
        return cache_path.read_text(encoding="utf-8")
    response = SESSION.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    cache_path.write_text(response.text, encoding="utf-8")
    return response.text


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_comment_count(value: str) -> int:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def parse_tips_summary(value: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def looks_like_market_label(value: str) -> bool:
    market_terms = {"win match", "draw no bet", "money line", "outright winner", "group betting", "run line", "game totals"}
    return value.lower() in market_terms


def normalize_team_label(sport: str, raw_label: str) -> str:
    cleaned = clean_text(raw_label).lower()
    cleaned = cleaned.replace("st. ", "st ")
    alias_map = BASEBALL_TEAM_ALIASES if sport == "baseball" else NBA_TEAM_ALIASES
    if cleaned in alias_map:
        return alias_map[cleaned]
    return alias_map.get(cleaned.split()[-1], cleaned)


def build_matchup_key(sport: str, event_name: str) -> list[str] | None:
    separator = " @ " if " @ " in event_name else " vs " if " vs " in event_name else None
    if not separator:
        return None
    left, right = event_name.split(separator, 1)
    return sorted([normalize_team_label(sport, left), normalize_team_label(sport, right)])


def parse_event_card(card: Tag) -> dict[str, Any]:
    link = card.select_one('a[itemprop="url"]')
    time_tag = card.select_one('time[itemprop="startDate"]')
    event_name = clean_text(card.select_one('[itemprop="name"]').get_text(" ", strip=True))
    competition = clean_text(link.find_next("p").get_text(" ", strip=True)) if link and link.find_next("p") else ""
    if looks_like_market_label(competition):
        competition = ""

    selection_node = None
    for heading in card.find_all("h4"):
        text = clean_text(heading.get_text(" ", strip=True))
        if text:
            selection_node = heading
            break
    selection = clean_text(selection_node.get_text(" ", strip=True)) if selection_node else ""
    market = clean_text(selection_node.find_next("p").get_text(" ", strip=True)) if selection_node and selection_node.find_next("p") else ""

    odds_node = card.select_one(".ui-odds")
    odds = {
        "decimal": odds_node.get("data-decimal") if odds_node else None,
        "american": odds_node.get("data-american") if odds_node else None,
        "fractional": odds_node.get("data-fractional") if odds_node else None,
    }

    spans = [clean_text(span.get_text(" ", strip=True)) for span in card.find_all("span")]
    percent = next((item for item in spans if item.endswith("%")), "")
    comment_text = next((item for item in spans if "comment" in item.lower()), "")
    tips_text = next((item for item in spans if "win tips" in item.lower()), "")
    for p_tag in card.find_all("p"):
        text = clean_text(p_tag.get_text(" ", strip=True))
        if "Win Tips" in text or "tips" in text.lower():
            tips_text = text
            break

    href = link["href"] if link and link.has_attr("href") else ""
    event_id_match = re.search(r"event_id=(\d+)", href)
    win_tips, total_tips = parse_tips_summary(tips_text)

    return {
        "event_id": event_id_match.group(1) if event_id_match else None,
        "event_name": event_name,
        "competition": competition,
        "event_url": href,
        "start_label": clean_text(time_tag.get_text(" ", strip=True)) if time_tag else "",
        "start_datetime": time_tag.get("datetime") if time_tag else None,
        "featured_selection": selection,
        "featured_market": market,
        "odds": odds,
        "tips_summary": tips_text,
        "win_tips": win_tips,
        "total_tips": total_tips,
        "consensus_percent": percent,
        "comment_count": parse_comment_count(comment_text),
    }


def parse_board(html: str, page_url: str, sport: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for event in soup.select('[itemscope][itemtype="http://schema.org/SportsEvent"]'):
        li = event.find_parent("li")
        if not li:
            continue
        cards.append(parse_event_card(li))

    fixtures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        event_id = str(card.get("event_id") or "")
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        fixtures.append(
            {
                "event_id": card["event_id"],
                "event_name": card["event_name"],
                "matchup_key": build_matchup_key(sport, card["event_name"]),
                "competition": card["competition"],
                "event_url": card["event_url"],
                "start_label": card["start_label"],
                "start_datetime": card["start_datetime"],
            }
        )

    return {
        "sport": sport,
        "page_url": page_url,
        "scraped_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture_count": len(fixtures),
        "tip_card_count": len(cards),
        "fixtures": fixtures,
        "tip_cards": cards,
    }


def default_output_path(sport: str, fmt: str) -> Path:
    folder = BASE_DIR / SPORT_CONFIG[sport]["folder"] / "outputs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"olbg_{sport}_board.{fmt}"


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        f"# OLBG {payload['sport'].title()} Board",
        "",
        f"- Source: {payload['page_url']}",
        f"- Scraped At UTC: {payload['scraped_at_utc']}",
        f"- Fixtures: {payload['fixture_count']}",
        f"- Tip Cards: {payload['tip_card_count']}",
        "",
        "## Fixtures",
        "",
        "| Event | Competition | Start | Event ID |",
        "|---|---|---|---|",
    ]
    for item in payload["fixtures"]:
        lines.append(
            f"| {item['event_name']} | {item['competition']} | {item['start_label']} | {item['event_id'] or ''} |"
        )
    lines.extend(["", "## Tip Cards", "", "| Event | Pick | Market | Odds | Tips | Consensus |", "|---|---|---|---|---|---|"])
    for item in payload["tip_cards"]:
        odds = item["odds"]["decimal"] or item["odds"]["american"] or ""
        lines.append(
            f"| {item['event_name']} | {item['featured_selection']} | {item['featured_market']} | {odds} | {item['tips_summary']} | {item['consensus_percent']} |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache OLBG event boards.")
    parser.add_argument("--sport", choices=sorted(SPORT_CONFIG), required=True)
    parser.add_argument("--cache-minutes", type=int, default=10)
    parser.add_argument("--format", choices=("json", "md", "both"), default="both")
    parser.add_argument("--output", help="Optional output path for JSON or markdown.")
    args = parser.parse_args()

    config = SPORT_CONFIG[args.sport]
    html = fetch_html(args.sport, config["url"], args.cache_minutes)
    payload = parse_board(html, config["url"], args.sport)

    written: list[Path] = []
    if args.format in {"json", "both"}:
        json_path = Path(args.output) if args.output and args.format == "json" else default_output_path(args.sport, "json")
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(json_path)
    if args.format in {"md", "both"}:
        md_path = Path(args.output) if args.output and args.format == "md" else default_output_path(args.sport, "md")
        write_markdown(md_path, payload)
        written.append(md_path)

    print(json.dumps({"sport": payload["sport"], "fixture_count": payload["fixture_count"], "tip_card_count": payload["tip_card_count"]}, indent=2))
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
