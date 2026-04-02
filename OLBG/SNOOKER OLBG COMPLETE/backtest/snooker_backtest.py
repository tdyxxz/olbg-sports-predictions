import argparse
import csv
from collections import defaultdict
from pathlib import Path


def load_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value, default=0.0):
    text = (value or "").strip()
    return float(text) if text else default


def as_int(value, default=0):
    text = (value or "").strip()
    return int(text) if text else default


def normalize_winner(value):
    winner = (value or "").strip().lower()
    if winner not in {"player_a", "player_b"}:
        raise ValueError(f"winner must be 'player_a' or 'player_b', got: {value}")
    return winner


def novig_probs(odds_a, odds_b):
    raw_a = 1.0 / odds_a
    raw_b = 1.0 / odds_b
    total = raw_a + raw_b
    return raw_a / total, raw_b / total


def settle_profit(winner, selection, odds, stake):
    return stake * (odds - 1.0) if winner == selection else -stake


def odds_bucket(odds):
    if odds < 1.45:
        return "<1.45"
    if odds < 1.80:
        return "1.45-1.79"
    if odds < 2.20:
        return "1.80-2.19"
    if odds < 3.00:
        return "2.20-2.99"
    return "3.00+"


def clv_percent(price_taken, close_odds):
    if not price_taken or not close_odds:
        return 0.0
    return (price_taken / close_odds - 1.0) * 100.0


def summarize(rows, label):
    bets = len(rows)
    wins = sum(1 for row in rows if row["won"])
    stake = sum(row["stake"] for row in rows)
    profit = sum(row["profit"] for row in rows)
    roi = (profit / stake * 100.0) if stake else 0.0
    avg_edge = (sum(row["edge"] for row in rows) / bets * 100.0) if bets else 0.0
    avg_clv = (sum(row["clv_pct"] for row in rows) / bets) if bets else 0.0
    avg_odds = (sum(row["odds"] for row in rows) / bets) if bets else 0.0

    return {
        "label": label,
        "bets": bets,
        "wins": wins,
        "stake": stake,
        "profit": profit,
        "roi_pct": roi,
        "win_rate_pct": (wins / bets * 100.0) if bets else 0.0,
        "avg_edge_pct": avg_edge,
        "avg_clv_pct": avg_clv,
        "avg_odds": avg_odds,
    }


def print_table(title, summaries):
    print(title)
    print(
        f"{'Group':24} {'Bets':>6} {'Wins':>6} {'Stake':>8} {'Profit':>10} "
        f"{'ROI%':>8} {'Win%':>8} {'Edge%':>8} {'CLV%':>8} {'Odds':>8}"
    )
    for summary in summaries:
        print(
            f"{summary['label'][:24]:24} {summary['bets']:6d} {summary['wins']:6d} "
            f"{summary['stake']:8.2f} {summary['profit']:10.2f} {summary['roi_pct']:8.2f} "
            f"{summary['win_rate_pct']:8.2f} {summary['avg_edge_pct']:8.2f} "
            f"{summary['avg_clv_pct']:8.2f} {summary['avg_odds']:8.2f}"
        )
    print()


def evaluate_match(
    row,
    min_edge,
    min_model_prob,
    max_short_price,
    short_price_edge,
    max_odds,
    require_rankings,
    stake,
):
    model_prob_a = as_float(row["model_prob_a"])
    if not 0.0 < model_prob_a < 1.0:
        raise ValueError(f"model_prob_a must be between 0 and 1 for {row['event_id']}")

    close_odds_a = as_float(row["close_odds_a"])
    close_odds_b = as_float(row["close_odds_b"])
    if close_odds_a <= 1.0 or close_odds_b <= 1.0:
        raise ValueError(f"close odds must be > 1.0 for {row['event_id']}")

    price_taken_a = as_float(row["price_taken_a"], close_odds_a) or close_odds_a
    price_taken_b = as_float(row["price_taken_b"], close_odds_b) or close_odds_b

    close_prob_a, close_prob_b = novig_probs(close_odds_a, close_odds_b)
    model_prob_b = 1.0 - model_prob_a
    edge_a = model_prob_a - close_prob_a
    edge_b = model_prob_b - close_prob_b

    if edge_a >= edge_b:
        selection = "player_a"
        opponent = "player_b"
        model_prob = model_prob_a
        edge = edge_a
        odds = price_taken_a
        close_odds = close_odds_a
        player_name = row["player_a"]
        opponent_name = row["player_b"]
    else:
        selection = "player_b"
        opponent = "player_a"
        model_prob = model_prob_b
        edge = edge_b
        odds = price_taken_b
        close_odds = close_odds_b
        player_name = row["player_b"]
        opponent_name = row["player_a"]

    if edge < min_edge:
        return None
    if model_prob < min_model_prob:
        return None
    if odds < max_short_price and edge < short_price_edge:
        return None
    if max_odds and odds > max_odds:
        return None
    if require_rankings:
        rank_a = as_float(row.get("rank_a"))
        rank_b = as_float(row.get("rank_b"))
        if rank_a <= 0 or rank_b <= 0:
            return None

    winner = normalize_winner(row["winner"])
    won = winner == selection
    profit = settle_profit(winner, selection, odds, stake)

    return {
        "event_id": row["event_id"],
        "event_date": row["event_date"],
        "tournament": row["tournament"],
        "round": row["round"],
        "selection": selection,
        "player_name": player_name,
        "opponent_name": opponent_name,
        "won": won,
        "odds": odds,
        "close_odds": close_odds,
        "model_prob": model_prob,
        "market_prob": close_prob_a if selection == "player_a" else close_prob_b,
        "edge": edge,
        "clv_pct": clv_percent(odds, close_odds),
        "stake": stake,
        "profit": profit,
    }


def export_rows(path, rows):
    fieldnames = [
        "event_id",
        "event_date",
        "tournament",
        "round",
        "selection",
        "player_name",
        "opponent_name",
        "won",
        "odds",
        "close_odds",
        "model_prob",
        "market_prob",
        "edge",
        "clv_pct",
        "stake",
        "profit",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Backtest a snooker value-betting model.")
    parser.add_argument("--data", required=True, help="Path to the snooker value CSV")
    parser.add_argument("--min-edge", type=float, default=0.04, help="Minimum edge needed to bet")
    parser.add_argument(
        "--min-model-prob",
        type=float,
        default=0.54,
        help="Minimum model win probability needed to bet",
    )
    parser.add_argument(
        "--max-short-price",
        type=float,
        default=1.45,
        help="Odds shorter than this need the stricter short-price edge rule",
    )
    parser.add_argument(
        "--short-price-edge",
        type=float,
        default=0.08,
        help="Minimum edge for odds shorter than max-short-price",
    )
    parser.add_argument(
        "--max-odds",
        type=float,
        default=0.0,
        help="Optional maximum odds allowed for a bet. Use 0 to disable.",
    )
    parser.add_argument(
        "--require-rankings",
        action="store_true",
        help="Skip matches where rank_a or rank_b is missing or zero.",
    )
    parser.add_argument("--stake", type=float, default=1.0, help="Flat stake per bet")
    parser.add_argument("--export", default="", help="Optional path to export placed bets")
    args = parser.parse_args()

    rows = load_rows(Path(args.data))
    placed = []
    skipped = 0

    for row in rows:
        evaluated = evaluate_match(
            row=row,
            min_edge=args.min_edge,
            min_model_prob=args.min_model_prob,
            max_short_price=args.max_short_price,
            short_price_edge=args.short_price_edge,
            max_odds=args.max_odds,
            require_rankings=args.require_rankings,
            stake=args.stake,
        )
        if evaluated is None:
            skipped += 1
            continue
        placed.append(evaluated)

    print(f"Rows read: {len(rows)}")
    print(f"Bets placed: {len(placed)}")
    print(f"Rows skipped: {skipped}")
    print()

    overall = [summarize(placed, "Overall")]
    by_tournament = []
    tournament_groups = defaultdict(list)
    for row in placed:
        tournament_groups[row["tournament"]].append(row)
    for tournament in sorted(tournament_groups):
        by_tournament.append(summarize(tournament_groups[tournament], tournament))

    by_odds = []
    odds_groups = defaultdict(list)
    for row in placed:
        odds_groups[odds_bucket(row["odds"])].append(row)
    for bucket in sorted(odds_groups):
        by_odds.append(summarize(odds_groups[bucket], bucket))

    print_table("Overall", overall)
    print_table("By Tournament", by_tournament)
    print_table("By Odds Bucket", by_odds)

    if args.export:
        export_rows(args.export, placed)
        print(f"Placed bets exported to: {args.export}")


if __name__ == "__main__":
    main()
