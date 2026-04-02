from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
DATASET_PATH = OUTPUT_DIR / "moneyline_feature_dataset_v2_2023_2025.csv"
ROBUST_PATH = OUTPUT_DIR / "robust_weighted_regime_search.json"

FEATURE_NAMES = [
    "recent_win_edge",
    "recent_rd_edge",
    "season_win_edge",
    "season_rd_edge",
    "venue_win_edge",
    "venue_rd_edge",
    "starter_edge",
    "prev_ops_hand_edge",
    "prev_avg_hand_edge",
    "prev_bullpen_edge",
]


def implied_probability(odds: np.ndarray) -> np.ndarray:
    odds = odds.astype(float)
    out = np.empty_like(odds, dtype=float)
    pos = odds > 0
    out[pos] = 100.0 / (odds[pos] + 100.0)
    out[~pos] = (-odds[~pos]) / ((-odds[~pos]) + 100.0)
    return out


def settle_profit(odds: np.ndarray, won: np.ndarray) -> np.ndarray:
    odds = odds.astype(float)
    won = won.astype(bool)
    payout = np.where(odds > 0, odds / 100.0, 100.0 / (-odds))
    return np.where(won, payout, -1.0)


def odds_band_mask(name: str, odds: np.ndarray) -> np.ndarray:
    if name == "all":
        return np.ones_like(odds, dtype=bool)
    if name == "heavy_favorites":
        return odds <= -300
    if name == "favorites_200_plus":
        return odds <= -200
    if name == "mid_favorites":
        return (odds >= -199) & (odds <= -110)
    if name == "short_underdogs":
        return (odds > 100) & (odds <= 150)
    if name == "medium_underdogs":
        return (odds >= 151) & (odds <= 200)
    if name == "heavy_or_short_dog":
        return (odds <= -300) | ((odds > 100) & (odds <= 150))
    if name == "favorites_200_plus_or_short_dog":
        return (odds <= -200) | ((odds > 100) & (odds <= 150))
    raise ValueError(name)


def summarize(mask: np.ndarray, profits: np.ndarray, wins: np.ndarray) -> dict:
    count = int(mask.sum())
    if count == 0:
        return {"bets": 0, "profit": 0.0, "roi": 0.0, "win_rate": 0.0}
    selected_profit = profits[mask]
    return {
        "bets": count,
        "profit": float(selected_profit.sum()),
        "roi": float(selected_profit.mean()),
        "win_rate": float(wins[mask].mean()),
    }


def evaluate_candidate(frame: pd.DataFrame, candidate: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    away_open_odds = frame["away_open_odds"].to_numpy(dtype=int)
    home_open_odds = frame["home_open_odds"].to_numpy(dtype=int)
    away_win = frame["away_win"].to_numpy(dtype=int)
    market_away_prob = np.clip(frame["market_away_prob"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    market_logit = np.log(market_away_prob / (1.0 - market_away_prob))
    features = frame[FEATURE_NAMES].to_numpy(dtype=float)
    weights = np.array([candidate["weights"][name] for name in FEATURE_NAMES], dtype=float)

    adjustment = features @ weights
    away_prob = 1.0 / (1.0 + np.exp(-(market_logit + adjustment)))
    home_prob = 1.0 - away_prob
    away_edge = away_prob - implied_probability(away_open_odds)
    home_edge = home_prob - implied_probability(home_open_odds)
    take_away = away_edge >= home_edge
    selection_odds = np.where(take_away, away_open_odds, home_open_odds)
    selection_edge = np.where(take_away, away_edge, home_edge)
    selection_won = np.where(take_away, away_win == 1, away_win == 0)
    selection_profit = settle_profit(selection_odds, selection_won)
    mask = (selection_edge >= candidate["min_edge"]) & odds_band_mask(candidate["band"], selection_odds)
    return mask, selection_profit, selection_won.astype(float)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate top robust MLB candidates month by month.")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--start-month", default="2024-04")
    args = parser.parse_args()

    df = pd.read_csv(DATASET_PATH)
    df = df[(df["away_open_odds"] != 0) & (df["home_open_odds"] != 0)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)
    candidates = json.loads(ROBUST_PATH.read_text(encoding="utf-8"))[: args.top]

    results = []
    months = sorted(month for month in df["month"].unique().tolist() if month >= args.start_month)
    for index, candidate in enumerate(candidates, start=1):
        monthly = []
        positive_months = 0
        negative_months = 0
        total_bets = 0
        total_profit = 0.0
        for month in months:
            month_frame = df[df["month"] == month].copy()
            mask, profits, wins = evaluate_candidate(month_frame, candidate)
            summary = summarize(mask, profits, wins)
            monthly.append({"month": month, **summary})
            if summary["bets"] > 0:
                if summary["roi"] > 0:
                    positive_months += 1
                elif summary["roi"] < 0:
                    negative_months += 1
                total_bets += summary["bets"]
                total_profit += summary["profit"]

        results.append(
            {
                "rank": index,
                "band": candidate["band"],
                "min_edge": candidate["min_edge"],
                "weights": candidate["weights"],
                "test_roi_2024_2025": candidate["test_roi"],
                "aggregate": {
                    "bets": int(total_bets),
                    "profit": float(total_profit),
                    "roi": float(total_profit / total_bets) if total_bets else 0.0,
                    "positive_months": positive_months,
                    "negative_months": negative_months,
                    "push_months": len(months) - positive_months - negative_months,
                },
                "months": monthly,
            }
        )

    results.sort(
        key=lambda item: (
            item["aggregate"]["roi"],
            item["aggregate"]["positive_months"],
            -item["aggregate"]["negative_months"],
            item["aggregate"]["profit"],
        ),
        reverse=True,
    )

    out_path = OUTPUT_DIR / "robust_candidates_monthly.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results[:5], indent=2))
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    main()
