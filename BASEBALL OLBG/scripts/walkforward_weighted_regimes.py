from __future__ import annotations

import json
import math
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


def implied_probability(odds: np.ndarray) -> np.ndarray:
    odds = odds.astype(float)
    out = np.empty_like(odds, dtype=float)
    pos = odds > 0
    out[pos] = 100.0 / (odds[pos] + 100.0)
    out[~pos] = (-odds[~pos]) / ((-odds[~pos]) + 100.0)
    return out


def settle_profit(odds: np.ndarray, won: np.ndarray) -> np.ndarray:
    odds = odds.astype(float)
    payout = np.empty_like(odds, dtype=float)
    pos = odds > 0
    payout[pos] = odds[pos] / 100.0
    payout[~pos] = 100.0 / (-odds[~pos])
    return np.where(won.astype(bool), payout, -1.0)


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
    sel_profit = profits[mask]
    return {
        "bets": count,
        "profit": float(sel_profit.sum()),
        "roi": float(sel_profit.mean()),
        "win_rate": float(wins[mask].mean()),
    }


def score_rows(frame: pd.DataFrame, weights: np.ndarray, band: str, threshold: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    away_open_odds = frame["away_open_odds"].to_numpy(dtype=int)
    home_open_odds = frame["home_open_odds"].to_numpy(dtype=int)
    away_win = frame["away_win"].to_numpy(dtype=int)
    market_away_prob = np.clip(frame["market_away_prob"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    market_logit = np.log(market_away_prob / (1.0 - market_away_prob))
    features = frame[FEATURE_NAMES].to_numpy(dtype=float)

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
    mask = (selection_edge >= threshold) & odds_band_mask(band, selection_odds)
    return mask, selection_profit, selection_won.astype(float)


def search_train(frame: pd.DataFrame, iterations: int, seed: int, min_bets: int) -> dict:
    rng = np.random.default_rng(seed)
    thresholds = np.array([0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25], dtype=float)
    bands = [
        "all",
        "heavy_favorites",
        "favorites_200_plus",
        "mid_favorites",
        "short_underdogs",
        "medium_underdogs",
        "heavy_or_short_dog",
        "favorites_200_plus_or_short_dog",
    ]
    best = None
    for _ in range(iterations):
        weights = rng.uniform(-1.5, 1.5, size=len(FEATURE_NAMES))
        threshold = float(rng.choice(thresholds))
        band = str(rng.choice(bands))
        mask, profits, wins = score_rows(frame, weights, band, threshold)
        summary = summarize(mask, profits, wins)
        if summary["bets"] < min_bets:
            continue
        candidate = {
            "weights": weights.tolist(),
            "band": band,
            "min_edge": threshold,
            "summary": summary,
        }
        if best is None or (
            summary["roi"],
            summary["profit"],
            summary["bets"],
        ) > (
            best["summary"]["roi"],
            best["summary"]["profit"],
            best["summary"]["bets"],
        ):
            best = candidate
    return best


def evaluate_split(df: pd.DataFrame, train_seasons: list[int], test_seasons: list[int], seed: int) -> dict:
    train = df[df["season"].isin(train_seasons)].copy()
    test = df[df["season"].isin(test_seasons)].copy()
    best = search_train(train, iterations=3000, seed=seed, min_bets=25)
    weights = np.array(best["weights"], dtype=float)

    train_mask, train_profit, train_wins = score_rows(train, weights, best["band"], best["min_edge"])
    test_mask, test_profit, test_wins = score_rows(test, weights, best["band"], best["min_edge"])

    return {
        "train_seasons": train_seasons,
        "test_seasons": test_seasons,
        "best_regime": {
            "weights": {
                name: float(value)
                for name, value in zip(FEATURE_NAMES, best["weights"], strict=True)
            },
            "band": best["band"],
            "min_edge": best["min_edge"],
        },
        "train_summary": summarize(train_mask, train_profit, train_wins),
        "test_summary": summarize(test_mask, test_profit, test_wins),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATASET_PATH)
    df = df[(df["away_open_odds"] != 0) & (df["home_open_odds"] != 0)].copy()

    results = [
        evaluate_split(df, [2023], [2024], seed=11),
        evaluate_split(df, [2023, 2024], [2025], seed=29),
    ]

    out_path = OUTPUT_DIR / "weighted_regime_walkforward.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    main()
