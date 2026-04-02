import argparse
import csv
from collections import defaultdict
from pathlib import Path


VALID_RESULTS = {"win", "loss", "push", "void"}


def load_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def normalize_text(value):
    return (value or "").strip()


def normalize_key(row):
    return (
        normalize_text(row["event_id"]),
        normalize_text(row["market"]).lower(),
        normalize_text(row["selection"]).lower(),
    )


def odds_bucket(odds):
    if odds < 1.5:
        return "<1.50"
    if odds < 2.0:
        return "1.50-1.99"
    if odds < 3.0:
        return "2.00-2.99"
    if odds < 5.0:
        return "3.00-4.99"
    return "5.00+"


def settle_profit(result, odds, stake):
    if result == "win":
        return stake * (odds - 1.0)
    if result == "loss":
        return -stake
    if result in {"push", "void"}:
        return 0.0
    raise ValueError(f"Unsupported result: {result}")


def summarize(rows, label):
    settled = [r for r in rows if r["result"] not in {"void"}]
    bets = len(settled)
    wins = sum(1 for r in settled if r["result"] == "win")
    pushes = sum(1 for r in rows if r["result"] == "push")
    voids = sum(1 for r in rows if r["result"] == "void")
    stake = sum(r["stake_units"] for r in settled)
    profit = sum(r["profit"] for r in rows)
    roi = (profit / stake * 100.0) if stake else 0.0
    avg_odds = (sum(r["odds_decimal"] for r in settled) / bets) if bets else 0.0
    hit_rate = (wins / bets * 100.0) if bets else 0.0

    return {
        "label": label,
        "bets": bets,
        "wins": wins,
        "pushes": pushes,
        "voids": voids,
        "stake": stake,
        "profit": profit,
        "roi_pct": roi,
        "hit_rate_pct": hit_rate,
        "avg_odds": avg_odds,
    }


def print_summary_table(title, summaries):
    print(title)
    print(
        f"{'Group':30} {'Bets':>6} {'Wins':>6} {'Push':>6} {'Void':>6} "
        f"{'Stake':>8} {'Profit':>10} {'ROI%':>8} {'Hit%':>8} {'AvgOdds':>8}"
    )
    for s in summaries:
        print(
            f"{s['label'][:30]:30} {s['bets']:6d} {s['wins']:6d} {s['pushes']:6d} {s['voids']:6d} "
            f"{s['stake']:8.2f} {s['profit']:10.2f} {s['roi_pct']:8.2f} "
            f"{s['hit_rate_pct']:8.2f} {s['avg_odds']:8.2f}"
        )
    print()


def build_market_index(markets):
    index = {}
    for row in markets:
        key = normalize_key(row)
        if key in index:
            raise ValueError(f"Duplicate market outcome row for key: {key}")

        result = normalize_text(row["result"]).lower()
        if result not in VALID_RESULTS:
            raise ValueError(f"Invalid result '{result}' for key: {key}")

        index[key] = {
            "sport": normalize_text(row["sport"]),
            "event_date": normalize_text(row["event_date"]),
            "competition": normalize_text(row["competition"]),
            "event_name": normalize_text(row["event_name"]),
            "market": normalize_text(row["market"]),
            "selection": normalize_text(row["selection"]),
            "odds_decimal": float(row["odds_decimal"]),
            "bookmaker": normalize_text(row["bookmaker"]),
            "source_url": normalize_text(row["source_url"]),
            "result": result,
            "notes": normalize_text(row["notes"]),
        }
    return index


def settle_picks(picks, market_index):
    settled = []
    missing = []

    for pick in picks:
        key = normalize_key(pick)
        market = market_index.get(key)
        if market is None:
            missing.append(pick)
            continue

        stake = float(pick["stake_units"])
        profit = settle_profit(market["result"], market["odds_decimal"], stake)
        settled.append(
            {
                "pick_id": normalize_text(pick["pick_id"]),
                "strategy_name": normalize_text(pick["strategy_name"]),
                "sport": normalize_text(pick["sport"]),
                "event_id": normalize_text(pick["event_id"]),
                "event_date": normalize_text(pick["event_date"]),
                "market": normalize_text(pick["market"]),
                "selection": normalize_text(pick["selection"]),
                "confidence": normalize_text(pick["confidence"]).upper(),
                "stake_units": stake,
                "odds_decimal": market["odds_decimal"],
                "result": market["result"],
                "profit": profit,
                "bookmaker": market["bookmaker"],
                "competition": market["competition"],
                "event_name": market["event_name"],
            }
        )

    return settled, missing


def export_settled_csv(path, rows):
    fieldnames = [
        "pick_id",
        "strategy_name",
        "sport",
        "event_id",
        "event_date",
        "competition",
        "event_name",
        "market",
        "selection",
        "confidence",
        "stake_units",
        "odds_decimal",
        "result",
        "profit",
        "bookmaker",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Backtest normalized sports betting picks.")
    parser.add_argument("--markets", required=True, help="Path to historical markets CSV")
    parser.add_argument("--picks", required=True, help="Path to strategy picks CSV")
    parser.add_argument(
        "--export-settled",
        default="",
        help="Optional path to export settled picks CSV",
    )
    args = parser.parse_args()

    markets_path = Path(args.markets)
    picks_path = Path(args.picks)

    markets = load_csv(markets_path)
    picks = load_csv(picks_path)

    market_index = build_market_index(markets)
    settled, missing = settle_picks(picks, market_index)

    if missing:
        print("Missing market rows for these picks:")
        for row in missing:
            print(
                f"- pick_id={row['pick_id']} event_id={row['event_id']} "
                f"market={row['market']} selection={row['selection']}"
            )
        print()

    overall = [summarize(settled, "Overall")]

    by_sport = []
    sport_groups = defaultdict(list)
    for row in settled:
        sport_groups[row["sport"]].append(row)
    for sport in sorted(sport_groups):
        by_sport.append(summarize(sport_groups[sport], sport))

    by_conf = []
    conf_groups = defaultdict(list)
    for row in settled:
        conf_groups[row["confidence"]].append(row)
    for conf in sorted(conf_groups):
        by_conf.append(summarize(conf_groups[conf], conf))

    by_odds = []
    odds_groups = defaultdict(list)
    for row in settled:
        odds_groups[odds_bucket(row["odds_decimal"])].append(row)
    for bucket in sorted(odds_groups):
        by_odds.append(summarize(odds_groups[bucket], bucket))

    print_summary_table("Overall", overall)
    print_summary_table("By Sport", by_sport)
    print_summary_table("By Confidence", by_conf)
    print_summary_table("By Odds Bucket", by_odds)

    if args.export_settled:
        export_settled_csv(args.export_settled, settled)
        print(f"Settled picks exported to: {args.export_settled}")


if __name__ == "__main__":
    main()
