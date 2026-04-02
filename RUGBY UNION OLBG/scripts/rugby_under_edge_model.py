import argparse
from pathlib import Path

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from walkforward_rugby_model import build_features


FEATURE_COLUMNS = [
    "home_implied_prob",
    "away_implied_prob",
    "total_line",
    "home_prev_matches",
    "away_prev_matches",
    "home_last5_win_rate",
    "away_last5_win_rate",
    "home_last5_avg_margin",
    "away_last5_avg_margin",
    "home_last5_market_surprise",
    "away_last5_market_surprise",
    "home_last5_points_for",
    "away_last5_points_for",
    "home_last5_points_against",
    "away_last5_points_against",
    "home_last5_total_surprise",
    "away_last5_total_surprise",
    "home_venue_last5_win_rate",
    "away_venue_last5_win_rate",
    "competition_prior_total_avg",
    "total_line_vs_comp_avg",
    "market_surprise_diff",
    "margin_diff",
    "win_rate_diff",
    "combined_total_surprise",
    "combined_attack",
    "combined_defense_leak",
]


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="constant", fill_value=0.0)),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, C=0.5)),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward UNDER model for rugby union totals.")
    parser.add_argument("--csv", nargs="+", required=True)
    parser.add_argument("--edge-threshold", type=float, default=0.07)
    parser.add_argument("--min-total", type=float, default=46.5)
    parser.add_argument("--max-total", type=float, default=66.5)
    parser.add_argument("--max-comp-delta", type=float, default=2.0)
    parser.add_argument("--output-summary", required=True)
    parser.add_argument("--output-bets", required=True)
    args = parser.parse_args()

    combined = pd.concat([pd.read_csv(path) for path in args.csv], ignore_index=True).drop_duplicates(subset=["event_url"])
    df = build_features(combined)
    df = df.dropna(subset=["total_line", "over_odds_decimal", "under_odds_decimal"]).copy()
    df = df.loc[(df["home_prev_matches"] >= 2) & (df["away_prev_matches"] >= 2)].sort_values("match_date").reset_index(drop=True)
    df["over_hit"] = (df["total_points"] > df["total_line"]).astype(int)

    pipeline = build_pipeline()
    folds = [(0.50, 0.67), (0.67, 0.83), (0.83, 1.00)]

    fold_rows = []
    selected_bets = []

    for start_frac, end_frac in folds:
        train_end = int(len(df) * start_frac)
        test_end = int(len(df) * end_frac)
        train = df.iloc[:train_end].copy()
        test = df.iloc[train_end:test_end].copy()

        pipeline.fit(train[FEATURE_COLUMNS], train["over_hit"])
        test = test.copy()
        test["over_model_prob"] = pipeline.predict_proba(test[FEATURE_COLUMNS])[:, 1]
        test["under_model_prob"] = 1 - test["over_model_prob"]
        test["under_implied_prob"] = 1.0 / test["under_odds_decimal"]
        test["under_edge"] = test["under_model_prob"] - test["under_implied_prob"]

        bets = test.loc[
            (test["under_edge"] >= args.edge_threshold)
            & (test["total_line"] >= args.min_total)
            & (test["total_line"] <= args.max_total)
            & (test["total_line_vs_comp_avg"] <= args.max_comp_delta)
        ].copy()
        bets["won_under"] = (bets["total_points"] < bets["total_line"]).astype(int)
        bets["profit_units"] = ((bets["under_odds_decimal"] - 1.0) * bets["won_under"]) + (-1.0 * (1 - bets["won_under"]))
        bets["fold"] = f"{start_frac:.2f}-{end_frac:.2f}"

        profit = float(bets["profit_units"].sum())
        bet_count = int(len(bets))
        roi = (profit / bet_count) * 100.0 if bet_count else 0.0
        fold_rows.append(
            {
                "fold": f"{start_frac:.2f}-{end_frac:.2f}",
                "bets": bet_count,
                "profit_units": round(profit, 4),
                "roi_pct": round(roi, 2),
            }
        )
        if bet_count:
            selected_bets.append(
                bets[
                    [
                        "fold",
                        "match_date",
                        "competition",
                        "home_team",
                        "away_team",
                        "total_line",
                        "total_points",
                        "under_odds_decimal",
                        "under_edge",
                        "profit_units",
                    ]
                ]
            )

    summary = pd.DataFrame(fold_rows)
    summary.loc[len(summary)] = {
        "fold": "aggregate",
        "bets": int(summary["bets"].sum()),
        "profit_units": round(float(summary["profit_units"].sum()), 4),
        "roi_pct": round(
            (float(summary["profit_units"].sum()) / int(summary["bets"].sum()) * 100.0) if int(summary["bets"].sum()) else 0.0,
            2,
        ),
    }

    selected = pd.concat(selected_bets, ignore_index=True) if selected_bets else pd.DataFrame()

    summary_path = Path(args.output_summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)

    bets_path = Path(args.output_bets)
    bets_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(bets_path, index=False)

    print(summary.to_string(index=False))
    print("")
    print(
        f"Rule: UNDER when edge >= {args.edge_threshold}, total in [{args.min_total}, {args.max_total}], "
        f"line_vs_comp_avg <= {args.max_comp_delta}"
    )
    print(f"Saved summary to {summary_path}")
    print(f"Saved bets to {bets_path}")


if __name__ == "__main__":
    main()
