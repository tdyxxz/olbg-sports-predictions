from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
DATASET_PATH = OUTPUT_DIR / "moneyline_feature_dataset_v2_2023_2025.csv"

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

BAND_NAMES = [
    "all",
    "heavy_favorites",
    "favorites_200_plus",
    "mid_favorites",
    "short_underdogs",
    "medium_underdogs",
    "heavy_or_short_dog",
    "favorites_200_plus_or_short_dog",
]

THRESHOLDS = np.array([0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25], dtype=float)


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


def score_candidate(
    feature_matrix: np.ndarray,
    market_logit: np.ndarray,
    away_open_odds: np.ndarray,
    home_open_odds: np.ndarray,
    away_win: np.ndarray,
    weights: np.ndarray,
    band_name: str,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    adjustment = feature_matrix @ weights
    away_prob = 1.0 / (1.0 + np.exp(-(market_logit + adjustment)))
    home_prob = 1.0 - away_prob
    away_edge = away_prob - implied_probability(away_open_odds)
    home_edge = home_prob - implied_probability(home_open_odds)

    take_away = away_edge >= home_edge
    selection_odds = np.where(take_away, away_open_odds, home_open_odds)
    selection_edge = np.where(take_away, away_edge, home_edge)
    selection_won = np.where(take_away, away_win == 1, away_win == 0)
    selection_profit = settle_profit(selection_odds, selection_won)
    base_mask = (selection_edge >= threshold) & odds_band_mask(band_name, selection_odds)
    return base_mask, selection_profit, selection_won.astype(float)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for robust MLB walk-forward regimes.")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--min-bets-per-test", type=int, default=20)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATASET_PATH)
    df = df[(df["away_open_odds"] != 0) & (df["home_open_odds"] != 0)].copy()

    rng = np.random.default_rng(args.seed)
    away_open_odds = df["away_open_odds"].to_numpy(dtype=int)
    home_open_odds = df["home_open_odds"].to_numpy(dtype=int)
    away_win = df["away_win"].to_numpy(dtype=int)
    seasons = df["season"].to_numpy(dtype=int)
    market_away_prob = np.clip(df["market_away_prob"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    market_logit = np.log(market_away_prob / (1.0 - market_away_prob))
    feature_matrix = df[FEATURE_NAMES].to_numpy(dtype=float)

    fold_masks = {
        "2024": seasons == 2024,
        "2025": seasons == 2025,
    }

    results = []
    for _ in range(args.iterations):
        weights = rng.uniform(-1.5, 1.5, size=len(FEATURE_NAMES))
        threshold = float(rng.choice(THRESHOLDS))
        band_name = str(rng.choice(BAND_NAMES))

        base_mask, profits, wins = score_candidate(
            feature_matrix=feature_matrix,
            market_logit=market_logit,
            away_open_odds=away_open_odds,
            home_open_odds=home_open_odds,
            away_win=away_win,
            weights=weights,
            band_name=band_name,
            threshold=threshold,
        )

        fold_summaries = {}
        min_test_roi = float("inf")
        total_test_profit = 0.0
        total_test_bets = 0
        valid = True
        for label, fold_mask in fold_masks.items():
            summary = summarize(base_mask & fold_mask, profits, wins)
            fold_summaries[label] = summary
            if summary["bets"] < args.min_bets_per_test:
                valid = False
                break
            min_test_roi = min(min_test_roi, summary["roi"])
            total_test_profit += summary["profit"]
            total_test_bets += summary["bets"]

        if not valid:
            continue

        results.append(
            {
                "weights": {
                    name: float(value)
                    for name, value in zip(FEATURE_NAMES, weights, strict=True)
                },
                "band": band_name,
                "min_edge": threshold,
                "test_folds": fold_summaries,
                "test_bets": int(total_test_bets),
                "test_profit": float(total_test_profit),
                "test_roi": float(total_test_profit / total_test_bets) if total_test_bets else 0.0,
                "min_test_roi": float(min_test_roi),
            }
        )

    results.sort(
        key=lambda item: (
            item["min_test_roi"],
            item["test_roi"],
            item["test_profit"],
            item["test_bets"],
        ),
        reverse=True,
    )

    out_path = OUTPUT_DIR / "robust_weighted_regime_search.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results[:20], indent=2))
    print(f"Saved full results to {out_path}")


if __name__ == "__main__":
    main()
