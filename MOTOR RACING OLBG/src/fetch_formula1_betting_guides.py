import argparse
import csv
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from unicodedata import normalize


SITEMAP_INDEX_URL = "https://www.formula1.com/en/latest/article/sitemap.xml"
ARTICLE_URL_PATTERN = re.compile(
    r"https://www\.formula1\.com/en/latest/article/[^<]*betting[^<]*",
    re.IGNORECASE,
)

SUPPORTED_SECTIONS = {
    "### The odds for a podium finish": "podium_finish",
    "### The odds for a top-10 finish": "points_finish",
    "### The odds for a points finish": "points_finish",
    "### The odds for a top-six finish": "top_6_finish",
    "### The odds for a top 6 finish": "top_6_finish",
    "### The odds for the win": "race_win",
    "### The odds for fastest lap": "fastest_lap",
    "### The odds for the fastest lap": "fastest_lap",
    "### The odds for who will be fastest in Qualifying": "qualifying_fastest",
    "### What are the odds for the win?": "race_win",
    "### What are the odds for fastest in qualifying?": "qualifying_fastest",
    "### What are the odds for a podium finish?": "podium_finish",
    "### What are the odds for fastest lap?": "fastest_lap",
    "### Winner:": "race_win",
    "### Podium:": "podium_finish",
    "### Top 10:": "points_finish",
    "### Points finish:": "points_finish",
    "### Fastest lap:": "fastest_lap",
}

SECTION_START_PATTERN = re.compile(r"### [^\n]+")
SCRIPT_CHUNK_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.S,
)
ROW_PATTERN = re.compile(
    r'"children":"([^"]+)"\}\],\["\$","td".+?"children":"([^"]+)"',
    re.S,
)
BULLET_PATTERN = re.compile(
    r"(?:●|-)\s+__([^_]+?)__\s+([0-9]+(?:\.[0-9]+)?)",
    re.S,
)
TIP_PATTERN = re.compile(
    r"Tip:\s*([^(]+?)\s*\(Odds\s*[^,]+,\s*([0-9]+(?:\.[0-9]+)?)",
    re.I | re.S,
)


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Codex-F1-Profitability-Model/1.0",
            "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8")


def load_results_reference(path):
    if not path:
        return {"race_names_by_season": {}, "race_date_lookup": {}}
    with open(path, "r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    by_season = {}
    race_date_lookup = {}
    for row in rows:
        season = int(row["season"])
        by_season.setdefault(season, set()).add(row["race_name"])
        race_date_lookup[(season, row["race_name"])] = row["race_date"]
    return {"race_names_by_season": by_season, "race_date_lookup": race_date_lookup}


def normalized_slug(text):
    text = normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return text


def find_matching_race_name(headline, season, results_reference):
    candidates = sorted(results_reference["race_names_by_season"].get(season, set()), key=len, reverse=True)
    normalized_headline = normalized_slug(headline)
    alias_map = {
        "australia": "Australian Grand Prix",
        "china": "Chinese Grand Prix",
        "japan": "Japanese Grand Prix",
        "bahrain": "Bahrain Grand Prix",
        "saudi arabia": "Saudi Arabian Grand Prix",
        "miami": "Miami Grand Prix",
        "imola": "Emilia Romagna Grand Prix",
        "monaco": "Monaco Grand Prix",
        "spain": "Spanish Grand Prix",
        "canada": "Canadian Grand Prix",
        "austria": "Austrian Grand Prix",
        "sao paulo": "Sao Paulo Grand Prix",
        "monza": "Italian Grand Prix",
        "silverstone": "British Grand Prix",
        "baku": "Azerbaijan Grand Prix",
        "singapore": "Singapore Grand Prix",
        "spa": "Belgian Grand Prix",
        "belgium": "Belgian Grand Prix",
        "qatar": "Qatar Grand Prix",
        "austin": "United States Grand Prix",
        "mexico": "Mexico City Grand Prix",
        "las vegas": "Las Vegas Grand Prix",
        "abu dhabi": "Abu Dhabi Grand Prix",
        "marina bay": "Singapore Grand Prix",
        "zandvoort": "Dutch Grand Prix",
        "spielberg": "Austrian Grand Prix",
        "hungary": "Hungarian Grand Prix",
    }

    for race_name in candidates:
        race_name_normalized = normalized_slug(race_name)
        race_name_core = re.sub(r"\bgrand prix\b", "", race_name_normalized).strip()
        if race_name_normalized in normalized_headline:
            return race_name
        if race_name_core and race_name_core in normalized_headline:
            return race_name

    for alias, race_name in alias_map.items():
        if alias in normalized_headline and race_name in candidates:
            return race_name

    return ""


def load_sitemap_urls():
    sitemap_index = fetch_text(SITEMAP_INDEX_URL)
    shard_urls = re.findall(r"https://www\.formula1\.com/en/latest/articles/sitemap-\d+\.xml", sitemap_index)
    urls = []
    for shard_url in shard_urls:
        shard_content = fetch_text(shard_url)
        urls.extend(match.group(0) for match in ARTICLE_URL_PATTERN.finditer(shard_content))
    return sorted(set(urls))


def extract_metadata(html, url):
    for block in JSON_LD_PATTERN.findall(html):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if payload.get("@type") == "NewsArticle":
            return {
                "headline": payload.get("headline", ""),
                "description": payload.get("description", ""),
                "date_published": payload.get("datePublished", ""),
                "url": payload.get("url", url),
            }
    return {"headline": "", "description": "", "date_published": "", "url": url}


def decode_stream_chunks(html):
    chunks = []
    for match in SCRIPT_CHUNK_PATTERN.finditer(html):
        try:
            chunks.append(json.loads(f'"{match.group(1)}"'))
        except json.JSONDecodeError:
            continue
    return "".join(chunks)


def extract_section_rows(section_text):
    rows = []
    for participant, odds_text in ROW_PATTERN.findall(section_text):
        if participant in {"Driver", "Team", "Odds"}:
            continue
        try:
            odds_value = float(odds_text)
        except ValueError:
            continue
        rows.append((participant, odds_value))
    deduped = []
    seen = set()
    for participant, odds_value in rows:
        key = (participant, odds_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((participant, odds_value))
    if deduped:
        return deduped

    for participant_blob, odds_text in BULLET_PATTERN.findall(section_text):
        try:
            odds_value = float(odds_text)
        except ValueError:
            continue
        participants = [item.strip() for item in participant_blob.split(",")]
        for participant in participants:
            if participant:
                key = (participant, odds_value)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((participant, odds_value))
    if deduped:
        return deduped

    for participant_blob, odds_text in TIP_PATTERN.findall(section_text):
        try:
            odds_value = float(odds_text)
        except ValueError:
            continue
        participant = participant_blob.strip()
        participant = re.sub(r"\s+(?:to win|podium finish|top 10 finish|points finish|fastest lap)$", "", participant, flags=re.I)
        if participant:
            key = (participant, odds_value)
            if key not in seen:
                seen.add(key)
                deduped.append((participant, odds_value))
    return deduped


def extract_markets_from_stream(stream_text):
    matches = list(SECTION_START_PATTERN.finditer(stream_text))
    sections = {}
    for index, match in enumerate(matches):
        heading = match.group(0)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stream_text)
        section_text = stream_text[start:end]
        if heading in SUPPORTED_SECTIONS:
            sections[SUPPORTED_SECTIONS[heading]] = extract_section_rows(section_text)
    return sections


def build_rows(article_url, results_reference):
    html = fetch_text(article_url)
    metadata = extract_metadata(html, article_url)
    stream_text = decode_stream_chunks(html)
    if not stream_text:
        return []

    markets = extract_markets_from_stream(stream_text)
    if not markets:
        return []

    date_published = metadata["date_published"]
    season = datetime.fromisoformat(date_published.replace("Z", "+00:00")).year if date_published else 0
    race_name = find_matching_race_name(metadata["headline"], season, results_reference)
    event_date = results_reference["race_date_lookup"].get((season, race_name), "")

    rows = []
    for market, market_rows in markets.items():
        for participant, odds_value in market_rows:
            rows.append(
                {
                    "event_date": event_date,
                    "article_date": date_published[:10],
                    "season": season,
                    "race_name": race_name,
                    "headline": metadata["headline"],
                    "bookmaker": "Formula1.com guide",
                    "market": market,
                    "outcome": "yes",
                    "driver": participant,
                    "participant": participant,
                    "decimal_odds": f"{odds_value:.6f}",
                    "source_url": metadata["url"],
                }
            )
    return rows


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_date",
        "article_date",
        "season",
        "race_name",
        "headline",
        "bookmaker",
        "market",
        "outcome",
        "driver",
        "participant",
        "decimal_odds",
        "source_url",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Fetch official Formula1.com betting-guide odds tables.")
    parser.add_argument(
        "--output",
        default=str(Path("data") / "raw" / "formula1_betting_guide_odds.csv"),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--results-reference",
        default=str(Path("data") / "raw" / "f1_results.csv"),
        help="Optional normalized results CSV used to map article headlines to official race names.",
    )
    parser.add_argument(
        "--start-season",
        type=int,
        default=2023,
        help="Minimum article season to keep.",
    )
    parser.add_argument(
        "--end-season",
        type=int,
        default=2026,
        help="Maximum article season to keep.",
    )
    args = parser.parse_args()

    results_reference = load_results_reference(args.results_reference)
    article_urls = load_sitemap_urls()

    all_rows = []
    for article_url in article_urls:
        rows = build_rows(article_url, results_reference)
        if not rows:
            continue
        season = rows[0]["season"]
        if season < args.start_season or season > args.end_season:
            continue
        all_rows.extend(rows)
        print(f"Parsed {len(rows)} rows from {article_url}")

    all_rows.sort(key=lambda row: (row["article_date"], row["race_name"], row["market"], row["participant"]))
    write_csv(all_rows, Path(args.output))
    print(f"Wrote {len(all_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
