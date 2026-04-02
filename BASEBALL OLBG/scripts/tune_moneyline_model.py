from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
DATASET_PATH = OUTPUT_DIR / "moneyline_feature_dataset_v2_2023_2025.csv"

FEATURE_COLUMNS = [
    "market_away_prob",
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


def american_to_probability(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)


def settle_american_bet(odds: int, won: bool) -> float:
    if not won:
        return -1.0
    if odds > 0:
        return odds / 100
    return 100 / (-odds)


def band_filter(name: str) -> Callable[[int], bool]:
    if name == "all":
        return lambda odds: True
    if name == "heavy_favorites":
        return lambda odds: odds <= -300
    if name == "favorites_200_plus":
        return lambda odds: odds <= -200
    if name == "mid_favorites":
        return lambda odds: -199 <= odds <= -110
    if name == "coin_flip":
        return lambda odds: -109 <= odds <= 100
    if name == "short_underdogs":
        return lambda odds: 100 < odds <= 150
    if name == "medium_underdogs":
        return lambda odds: 151 <= odds <= 200
    if name == "heavy_or_short_dog":
        return lambda odds: odds <= -300 or (100 < odds <= 150)
    raise ValueError(f"Unknown band: {name}")


def select_bets(df: pd.DataFrame, min_edge: float, band_name: str) -> pd.DataFrame:
    matcher = band_filter(band_name)
    mask = (df["selection_edge"] >= min_edge) & df["selection_odds"].map(matcher)
    return df.loc[mask].copy()


def summarize_bets(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "bets": 0,
            "profit_units": 0.0,
            "roi": 0.0,
            "win_rate": 0.0,
            "avg_edge": 0.0,
            "avg_clv": 0.0,
        }
    return {
        "bets": int(len(df)),
        "profit_units": float(df["profit"].sum()),
        "roi": float(df["profit"].mean()),
        "win_rate": float(df["won"].mean()),
        "avg_edge": float(df["selection_edge"].mean()),
        "avg_clv": float(df["clv"].mean()),
    }


def prepare_scored_frame(df: pd.DataFrame, away_probability: np.ndarray) -> pd.DataFrame:
    frame = df.copy()
    frame["pred_away_prob"] = away_probability
    frame["pred_home_prob"] = 1.0 - frame["pred_away_prob"]
    frame["away_open_prob"] = frame["away_open_odds"].map(american_to_probability)
    frame["home_open_prob"] = frame["home_open_odds"].map(american_to_probability)
    frame["away_close_prob"] = frame["away_close_odds"].map(american_to_probability)
    frame["home_close_prob"] = frame["home_close_odds"].map(american_to_probability)
    frame["away_edge"] = frame["pred_away_prob"] - frame["away_open_prob"]
    frame["home_edge"] = frame["pred_home_prob"] - frame["home_open_prob"]

    take_away = frame["away_edge"] >= frame["home_edge"]
    frame["selection_side"] = np.where(take_away, "away", "home")
    frame["selection_team"] = np.where(take_away, frame["away_team"], frame["home_team"])
    frame["selection_odds"] = np.where(take_away, frame["away_open_odds"], frame["home_open_odds"])
    frame["selection_edge"] = np.where(take_away, frame["away_edge"], frame["home_edge"])
    frame["won"] = np.where(take_away, frame["away_win"], 1 - frame["away_win"]).astype(int)
    frame["profit"] = [
        settle_american_bet(int(odds), bool(won))
        for odds, won in zip(frame["selection_odds"], frame["won"], strict=True)
    ]
    frame["clv"] = np.where(
        take_away,
        frame["away_close_prob"] - frame["away_open_prob"],
        frame["home_close_prob"] - frame["home_open_prob"],
    )
    return frame


def search_training_regime(train_scored: pd.DataFrame) -> dict:
    band_names = [
        "all",
        "heavy_favorites",
        "favorites_200_plus",
        "mid_favorites",
        "coin_flip",
        "short_underdogs",
        "medium_underdogs",
        "heavy_or_short_dog",
    ]
    thresholds = [round(x, 2) for x in np.arange(0.02, 0.31, 0.02)]
    candidates = []

    for band_name in band_names:
        for threshold in thresholds:
            bets = select_bets(train_scored, threshold, band_name)
            summary = summarize_bets(bets)
            if summary["bets"] < 25:
                continue
            # Favor positive ROI, positive CLV, and enough volume to matter.
            score = (
                summary["roi"] * 100
                + max(summary["avg_clv"], 0.0) * 25
                + min(summary["bets"], 200) / 200
            )
            candidates.append(
                {
                    "band": band_name,
                    "min_edge": threshold,
                    "train_summary": summary,
                    "score": score,
                }
            )

    candidates.sort(
        key=lambda item: (
            item["train_summary"]["roi"],
            item["train_summary"]["profit_units"],
            item["train_summary"]["avg_clv"],
            item["train_summary"]["bets"],
        ),
        reverse=True,
    )
    return candidates[0] if candidates else {"band": "all", "min_edge": 0.50, "train_summary": summarize_bets(train_scored.iloc[0:0]), "score": -999.0}


def run_split(df: pd.DataFrame, train_seasons: list[int], test_seasons: list[int]) -> dict:
    train = df[df["season"].isin(train_seasons)].copy()
    test = df[df["season"].isin(test_seasons)].copy()

    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logreg", LogisticRegression(max_iter=500, C=0.5)),
        ]
    )
    model.fit(train[FEATURE_COLUMNS], train["away_win"])

    train_probs = model.predict_proba(train[FEATURE_COLUMNS])[:, 1]
    test_probs = model.predict_proba(test[FEATURE_COLUMNS])[:, 1]

    train_scored = prepare_scored_frame(train, train_probs)
    test_scored = prepare_scored_frame(test, test_probs)

    best_regime = search_training_regime(train_scored)
    train_bets = select_bets(train_scored, best_regime["min_edge"], best_regime["band"])
    test_bets = select_bets(test_scored, best_regime["min_edge"], best_regime["band"])

    coeffs = model.named_steps["logreg"].coef_[0]
    coefficient_map = {
        name: float(value)
        for name, value in zip(FEATURE_COLUMNS, coeffs, strict=True)
    }

    return {
        "train_seasons": train_seasons,
        "test_seasons": test_seasons,
        "best_regime": {
            "band": best_regime["band"],
            "min_edge": best_regime["min_edge"],
        },
        "train_summary": summarize_bets(train_bets),
        "test_summary": summarize_bets(test_bets),
        "cofficients": coefficient_map,
        "intercept": float(model.named_steps["logreg"].intercept_[0]),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATASET_PATH)

    walk_forward_results = [
        run_split(df, [2023], [2024]),
        run_split(df, [2023, 2024], [2025]),
    ]

    out_path = OUTPUT_DIR / "moneyline_tuning_walkforward.json"
    out_path.write_text(json.dumps(walk_forward_results, indent=2), encoding="utf-8")

    print(json.dumps(walk_forward_results, indent=2))
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    main()
