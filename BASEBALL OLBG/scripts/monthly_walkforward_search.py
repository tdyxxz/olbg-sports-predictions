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


def search_train(
    train: pd.DataFrame,
    iterations: int,
    seed: int,
    min_train_bets: int,
) -> dict | None:
    rng = np.random.default_rng(seed)
    away_open_odds = train["away_open_odds"].to_numpy(dtype=int)
    home_open_odds = train["home_open_odds"].to_numpy(dtype=int)
    away_win = train["away_win"].to_numpy(dtype=int)
    seasons = train["season"].to_numpy(dtype=int)
    market_away_prob = np.clip(train["market_away_prob"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    market_logit = np.log(market_away_prob / (1.0 - market_away_prob))
    feature_matrix = train[FEATURE_NAMES].to_numpy(dtype=float)

    best: dict | None = None
    for _ in range(iterations):
        weights = rng.uniform(-1.5, 1.5, size=len(FEATURE_NAMES))
        threshold = float(rng.choice(THRESHOLDS))
        band_name = str(rng.choice(BAND_NAMES))
        mask, profits, wins = score_candidate(
            feature_matrix=feature_matrix,
            market_logit=market_logit,
            away_open_odds=away_open_odds,
            home_open_odds=home_open_odds,
            away_win=away_win,
            weights=weights,
            band_name=band_name,
            threshold=threshold,
        )
        train_summary = summarize(mask, profits, wins)
        if train_summary["bets"] < min_train_bets:
            continue

        by_year = {}
        min_year_roi = 999.0
        for season in sorted(set(seasons.tolist())):
            year_summary = summarize(mask & (seasons == season), profits, wins)
            by_year[str(season)] = year_summary
            if year_summary["bets"] > 0:
                min_year_roi = min(min_year_roi, year_summary["roi"])
        if min_year_roi == 999.0:
            min_year_roi = 0.0

        score = (
            train_summary["roi"] * 100
            + min_year_roi * 60
            + min(train_summary["bets"], 300) / 25
        )
        candidate = {
            "weights": {name: float(value) for name, value in zip(FEATURE_NAMES, weights, strict=True)},
            "band": band_name,
            "min_edge": threshold,
            "train_summary": train_summary,
            "train_by_year": by_year,
            "min_year_roi": float(min_year_roi),
            "score": float(score),
        }
        if best is None or (
            candidate["score"],
            candidate["train_summary"]["roi"],
            candidate["min_year_roi"],
            candidate["train_summary"]["profit"],
        ) > (
            best["score"],
            best["train_summary"]["roi"],
            best["min_year_roi"],
            best["train_summary"]["profit"],
        ):
            best = candidate
    return best


def evaluate_candidate(frame: pd.DataFrame, candidate: dict) -> dict:
    away_open_odds = frame["away_open_odds"].to_numpy(dtype=int)
    home_open_odds = frame["home_open_odds"].to_numpy(dtype=int)
    away_win = frame["away_win"].to_numpy(dtype=int)
    market_away_prob = np.clip(frame["market_away_prob"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    market_logit = np.log(market_away_prob / (1.0 - market_away_prob))
    feature_matrix = frame[FEATURE_NAMES].to_numpy(dtype=float)
    weights = np.array([candidate["weights"][name] for name in FEATURE_NAMES], dtype=float)
    mask, profits, wins = score_candidate(
        feature_matrix=feature_matrix,
        market_logit=market_logit,
        away_open_odds=away_open_odds,
        home_open_odds=home_open_odds,
        away_win=away_win,
        weights=weights,
        band_name=candidate["band"],
        threshold=float(candidate["min_edge"]),
    )
    return summarize(mask, profits, wins)


def main() -> None:
    parser = argparse.ArgumentParser(description="Anchored monthly walk-forward search for MLB moneyline regimes.")
    parser.add_argument("--iterations", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--min-train-bets", type=int, default=60)
    parser.add_argument("--start-month", default="2024-04")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATASET_PATH)
    df = df[(df["away_open_odds"] != 0) & (df["home_open_odds"] != 0)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)

    months = sorted(month for month in df["month"].unique().tolist() if month >= args.start_month)
    walkforward = []

    for idx, month in enumerate(months):
        test_mask = df["month"] == month
        train_mask = df["date"] < pd.Period(month).start_time
        train = df.loc[train_mask].copy()
        test = df.loc[test_mask].copy()
        if train.empty or test.empty:
            continue

        candidate = search_train(
            train=train,
            iterations=args.iterations,
            seed=args.seed + idx,
            min_train_bets=args.min_train_bets,
        )
        if not candidate:
            walkforward.append(
                {
                    "month": month,
                    "candidate": None,
                    "test_summary": {"bets": 0, "profit": 0.0, "roi": 0.0, "win_rate": 0.0},
                }
            )
            continue

        test_summary = evaluate_candidate(test, candidate)
        walkforward.append(
            {
                "month": month,
                "candidate": candidate,
                "test_summary": test_summary,
            }
        )

    total_bets = sum(item["test_summary"]["bets"] for item in walkforward)
    total_profit = sum(item["test_summary"]["profit"] for item in walkforward)
    positive_months = sum(1 for item in walkforward if item["test_summary"]["roi"] > 0)
    negative_months = sum(1 for item in walkforward if item["test_summary"]["roi"] < 0)
    summary = {
        "months": len(walkforward),
        "positive_months": positive_months,
        "negative_months": negative_months,
        "push_months": len(walkforward) - positive_months - negative_months,
        "bets": int(total_bets),
        "profit": float(total_profit),
        "roi": float(total_profit / total_bets) if total_bets else 0.0,
    }

    payload = {
        "config": {
            "iterations": args.iterations,
            "seed": args.seed,
            "min_train_bets": args.min_train_bets,
            "start_month": args.start_month,
        },
        "summary": summary,
        "months": walkforward,
    }

    out_path = OUTPUT_DIR / "monthly_walkforward_search.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    main()
