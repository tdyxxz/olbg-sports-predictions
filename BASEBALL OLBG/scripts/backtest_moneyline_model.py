from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = BASE_DIR / "data" / "historical" / "mlb_odds_dataset.json"
OUTPUT_DIR = BASE_DIR / "outputs"


def american_to_probability(odds: int) -> float:
    if odds == 0:
        return 0.0
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)


def probability_to_logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def logit_to_probability(logit: float) -> float:
    return 1 / (1 + math.exp(-logit))


def settle_american_bet(odds: int, won: bool) -> float:
    if not won:
        return -1.0
    if odds > 0:
        return odds / 100
    return 100 / (-odds)


def normalize_team_name(name: str) -> str:
    return (
        name.lower()
        .replace("st. ", "st ")
        .replace("d-backs", "diamondbacks")
        .strip()
    )


@dataclass
class TeamState:
    season: int | None = None
    season_wins: int = 0
    season_losses: int = 0
    season_runs_for: int = 0
    season_runs_against: int = 0
    recent_results: deque[tuple[bool, int]] | None = None

    def __post_init__(self) -> None:
        if self.recent_results is None:
            self.recent_results = deque(maxlen=10)

    def reset_for_new_season(self, season: int) -> None:
        self.season = season
        self.season_wins = 0
        self.season_losses = 0
        self.season_runs_for = 0
        self.season_runs_against = 0
        self.recent_results = deque(maxlen=10)

    def record(self, runs_for: int, runs_against: int) -> None:
        if runs_for > runs_against:
            self.season_wins += 1
        else:
            self.season_losses += 1
        self.season_runs_for += runs_for
        self.season_runs_against += runs_against
        self.recent_results.append((runs_for > runs_against, runs_for - runs_against))

    def season_win_pct(self) -> float:
        games = self.season_wins + self.season_losses
        return self.season_wins / games if games else 0.5

    def season_run_diff_pg(self) -> float:
        games = self.season_wins + self.season_losses
        if not games:
            return 0.0
        return (self.season_runs_for - self.season_runs_against) / games

    def recent_win_pct(self) -> float:
        if not self.recent_results:
            return 0.5
        return sum(1 for won, _ in self.recent_results if won) / len(self.recent_results)

    def recent_run_diff_pg(self) -> float:
        if not self.recent_results:
            return 0.0
        return sum(diff for _, diff in self.recent_results) / len(self.recent_results)


def consensus_american_odds(books: list[dict[str, Any]], side: str, line_type: str) -> int | None:
    values: list[int] = []
    for book in books:
        line = book.get(line_type)
        if not line:
            continue
        value = line.get(side)
        if value is None:
            continue
        values.append(int(value))
    if not values:
        return None
    return int(round(median(values)))


def load_games() -> list[dict[str, Any]]:
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    games: list[dict[str, Any]] = []
    for day, entries in raw.items():
        for entry in entries:
            game_view = entry.get("gameView", {})
            odds = entry.get("odds", {})
            moneyline_books = odds.get("moneyline") or []

            open_home = consensus_american_odds(moneyline_books, "homeOdds", "openingLine")
            open_away = consensus_american_odds(moneyline_books, "awayOdds", "openingLine")
            close_home = consensus_american_odds(moneyline_books, "homeOdds", "currentLine")
            close_away = consensus_american_odds(moneyline_books, "awayOdds", "currentLine")
            if None in (open_home, open_away, close_home, close_away):
                continue
            if 0 in (open_home, open_away, close_home, close_away):
                continue

            away_score = game_view.get("awayTeamScore")
            home_score = game_view.get("homeTeamScore")
            if away_score is None or home_score is None:
                continue

            start = datetime.fromisoformat(game_view["startDate"].replace("Z", "+00:00"))
            games.append(
                {
                    "date": day,
                    "season": int(day[:4]),
                    "start": start,
                    "away_team": normalize_team_name(game_view["awayTeam"]["fullName"]),
                    "home_team": normalize_team_name(game_view["homeTeam"]["fullName"]),
                    "away_team_display": game_view["awayTeam"]["fullName"],
                    "home_team_display": game_view["homeTeam"]["fullName"],
                    "away_score": int(away_score),
                    "home_score": int(home_score),
                    "open_home": open_home,
                    "open_away": open_away,
                    "close_home": close_home,
                    "close_away": close_away,
                }
            )

    games.sort(key=lambda item: item["start"])
    return games


def model_probability(
    away_state: TeamState,
    home_state: TeamState,
    open_away_odds: int,
    open_home_odds: int,
) -> float:
    away_market_prob = american_to_probability(open_away_odds)
    home_market_prob = american_to_probability(open_home_odds)
    market_prob = away_market_prob / (away_market_prob + home_market_prob)
    market_logit = probability_to_logit(market_prob)

    away_recent_edge = away_state.recent_win_pct() - home_state.recent_win_pct()
    away_recent_rd_edge = max(-3.0, min(3.0, away_state.recent_run_diff_pg() - home_state.recent_run_diff_pg()))
    away_season_edge = away_state.season_win_pct() - home_state.season_win_pct()
    away_season_rd_edge = max(-3.5, min(3.5, away_state.season_run_diff_pg() - home_state.season_run_diff_pg()))

    adjusted_logit = (
        market_logit
        + 0.55 * away_recent_edge
        + 0.12 * away_recent_rd_edge
        + 0.45 * away_season_edge
        + 0.10 * away_season_rd_edge
        - 0.10
    )
    return logit_to_probability(adjusted_logit)


def max_drawdown(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest a first-pass MLB moneyline model.")
    parser.add_argument("--min-edge", type=float, default=0.04, help="Minimum edge threshold to place a bet.")
    parser.add_argument(
        "--min-games",
        type=int,
        default=8,
        help="Minimum combined recent+season games required before a team can generate a signal.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    games = load_games()
    team_states: dict[str, TeamState] = defaultdict(TeamState)

    bets: list[dict[str, Any]] = []
    bankroll_curve = [0.0]
    bankroll = 0.0

    for game in games:
        season = game["season"]
        away = team_states[game["away_team"]]
        home = team_states[game["home_team"]]
        if away.season != season:
            away.reset_for_new_season(season)
        if home.season != season:
            home.reset_for_new_season(season)

        away_games_seen = away.season_wins + away.season_losses + len(away.recent_results)
        home_games_seen = home.season_wins + home.season_losses + len(home.recent_results)
        if away_games_seen >= args.min_games and home_games_seen >= args.min_games:
            away_prob = model_probability(away, home, game["open_away"], game["open_home"])
            home_prob = 1.0 - away_prob

            away_open_prob = american_to_probability(game["open_away"])
            home_open_prob = american_to_probability(game["open_home"])
            away_close_prob = american_to_probability(game["close_away"])
            home_close_prob = american_to_probability(game["close_home"])

            away_edge = away_prob - away_open_prob
            home_edge = home_prob - home_open_prob

            if away_edge >= home_edge:
                selection = "away"
                selection_team = game["away_team_display"]
                selection_edge = away_edge
                selection_prob = away_prob
                selection_odds = game["open_away"]
                clv = away_close_prob - away_open_prob
                won = game["away_score"] > game["home_score"]
            else:
                selection = "home"
                selection_team = game["home_team_display"]
                selection_edge = home_edge
                selection_prob = home_prob
                selection_odds = game["open_home"]
                clv = home_close_prob - home_open_prob
                won = game["home_score"] > game["away_score"]

            if selection_edge >= args.min_edge:
                profit = settle_american_bet(selection_odds, won)
                bankroll += profit
                bankroll_curve.append(bankroll)
                bets.append(
                    {
                        "date": game["date"],
                        "matchup": f"{game['away_team_display']} @ {game['home_team_display']}",
                        "selection_side": selection,
                        "selection_team": selection_team,
                        "opening_odds": selection_odds,
                        "model_probability": selection_prob,
                        "edge": selection_edge,
                        "clv": clv,
                        "won": won,
                        "profit": profit,
                    }
                )

        away.record(game["away_score"], game["home_score"])
        home.record(game["home_score"], game["away_score"])

    bets_count = len(bets)
    total_profit = sum(item["profit"] for item in bets)
    roi = total_profit / bets_count if bets_count else 0.0
    win_rate = mean(1.0 if item["won"] else 0.0 for item in bets) if bets else 0.0
    avg_edge = mean(item["edge"] for item in bets) if bets else 0.0
    avg_clv = mean(item["clv"] for item in bets) if bets else 0.0
    worst_drawdown = max_drawdown(bankroll_curve)

    summary = {
        "min_edge": args.min_edge,
        "min_games": args.min_games,
        "bets": bets_count,
        "profit_units": total_profit,
        "roi": roi,
        "win_rate": win_rate,
        "average_edge": avg_edge,
        "average_clv": avg_clv,
        "max_drawdown_units": worst_drawdown,
        "first_date": bets[0]["date"] if bets else None,
        "last_date": bets[-1]["date"] if bets else None,
    }

    summary_path = OUTPUT_DIR / "moneyline_backtest_summary.json"
    bets_path = OUTPUT_DIR / "moneyline_backtest_bets.json"
    report_path = OUTPUT_DIR / "moneyline_backtest_report.md"

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    bets_path.write_text(json.dumps(bets, indent=2), encoding="utf-8")

    report_lines = [
        "# MLB Moneyline Backtest",
        "",
        f"- Minimum edge: `{args.min_edge:.1%}`",
        f"- Minimum games before team is eligible: `{args.min_games}`",
        f"- Bets: `{bets_count}`",
        f"- Profit: `{total_profit:.2f}` units",
        f"- ROI: `{roi:.2%}`",
        f"- Win rate: `{win_rate:.2%}`",
        f"- Average edge: `{avg_edge:.2%}`",
        f"- Average CLV: `{avg_clv:.2%}`",
        f"- Max drawdown: `{worst_drawdown:.2f}` units",
        "",
        "## Recent Sample",
        "",
        "| Date | Matchup | Pick | Odds | Edge | CLV | Profit |",
        "|---|---|---|---:|---:|---:|---:|",
    ]

    for item in bets[-20:]:
        report_lines.append(
            f"| {item['date']} | {item['matchup']} | {item['selection_team']} | "
            f"{item['opening_odds']} | {item['edge']:.2%} | {item['clv']:.2%} | {item['profit']:.2f} |"
        )

    report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Summary: {summary_path}")
    print(f"Bets: {bets_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
