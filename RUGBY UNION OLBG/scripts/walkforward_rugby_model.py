import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class RuleResult:
    market: str
    rule: str
    train_bets: int
    train_profit: float
    train_roi: float
    test_bets: int
    test_profit: float
    test_roi: float


def profit_from_decimal(odds: float, won: bool) -> float:
    return (odds - 1.0) if won else -1.0


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    df["match_date"] = pd.to_datetime(df["match_date"])
    df = df.sort_values(["match_date", "competition", "home_team", "away_team"]).reset_index(drop=True)

    df["home_implied_prob"] = 1.0 / df["home_moneyline_decimal"]
    df["away_implied_prob"] = 1.0 / df["away_moneyline_decimal"]
    df["total_points"] = df["home_score"] + df["away_score"]
    df["home_win"] = (df["home_score"] > df["away_score"]).astype(float)
    df["away_win"] = (df["away_score"] > df["home_score"]).astype(float)
    df["home_margin"] = df["home_score"] - df["away_score"]
    df["away_margin"] = -df["home_margin"]
    df["home_market_surprise"] = df["home_win"] - df["home_implied_prob"]
    df["away_market_surprise"] = df["away_win"] - df["away_implied_prob"]
    df["total_surprise"] = df["total_points"] - df["total_line"]

    team_rows = []
    for _, row in df.iterrows():
        team_rows.append(
            {
                "match_date": row["match_date"],
                "competition": row["competition"],
                "team": row["home_team"],
                "venue_role": "HOME",
                "win": row["home_win"],
                "margin": row["home_margin"],
                "market_surprise": row["home_market_surprise"],
                "points_for": row["home_score"],
                "points_against": row["away_score"],
                "total_surprise": row["total_surprise"],
            }
        )
        team_rows.append(
            {
                "match_date": row["match_date"],
                "competition": row["competition"],
                "team": row["away_team"],
                "venue_role": "AWAY",
                "win": row["away_win"],
                "margin": row["away_margin"],
                "market_surprise": row["away_market_surprise"],
                "points_for": row["away_score"],
                "points_against": row["home_score"],
                "total_surprise": row["total_surprise"],
            }
        )

    team_df = pd.DataFrame(team_rows).sort_values(["team", "match_date"]).reset_index(drop=True)

    rolling_frames = []
    for team, group in team_df.groupby("team", sort=False):
        group = group.copy()
        shifted = group.shift(1)
        group["prev_matches"] = shifted["win"].expanding().count().fillna(0)
        group["last5_win_rate"] = shifted["win"].rolling(5, min_periods=1).mean()
        group["last5_avg_margin"] = shifted["margin"].rolling(5, min_periods=1).mean()
        group["last5_market_surprise"] = shifted["market_surprise"].rolling(5, min_periods=1).mean()
        group["last5_points_for"] = shifted["points_for"].rolling(5, min_periods=1).mean()
        group["last5_points_against"] = shifted["points_against"].rolling(5, min_periods=1).mean()
        group["last5_total_surprise"] = shifted["total_surprise"].rolling(5, min_periods=1).mean()

        home_shift = group.loc[group["venue_role"] == "HOME"].copy().shift(1)
        away_shift = group.loc[group["venue_role"] == "AWAY"].copy().shift(1)
        group.loc[group["venue_role"] == "HOME", "venue_last5_win_rate"] = home_shift["win"].rolling(5, min_periods=1).mean()
        group.loc[group["venue_role"] == "AWAY", "venue_last5_win_rate"] = away_shift["win"].rolling(5, min_periods=1).mean()
        rolling_frames.append(group)

    features = pd.concat(rolling_frames, ignore_index=True)

    home_features = features.loc[features["venue_role"] == "HOME"].copy()
    away_features = features.loc[features["venue_role"] == "AWAY"].copy()

    home_features = home_features.rename(
        columns={
            "team": "home_team",
            "prev_matches": "home_prev_matches",
            "last5_win_rate": "home_last5_win_rate",
            "last5_avg_margin": "home_last5_avg_margin",
            "last5_market_surprise": "home_last5_market_surprise",
            "last5_points_for": "home_last5_points_for",
            "last5_points_against": "home_last5_points_against",
            "last5_total_surprise": "home_last5_total_surprise",
            "venue_last5_win_rate": "home_venue_last5_win_rate",
        }
    )
    away_features = away_features.rename(
        columns={
            "team": "away_team",
            "prev_matches": "away_prev_matches",
            "last5_win_rate": "away_last5_win_rate",
            "last5_avg_margin": "away_last5_avg_margin",
            "last5_market_surprise": "away_last5_market_surprise",
            "last5_points_for": "away_last5_points_for",
            "last5_points_against": "away_last5_points_against",
            "last5_total_surprise": "away_last5_total_surprise",
            "venue_last5_win_rate": "away_venue_last5_win_rate",
        }
    )

    merge_cols = ["match_date", "competition", "home_team"]
    df = df.merge(
        home_features[
            merge_cols
            + [
                "home_prev_matches",
                "home_last5_win_rate",
                "home_last5_avg_margin",
                "home_last5_market_surprise",
                "home_last5_points_for",
                "home_last5_points_against",
                "home_last5_total_surprise",
                "home_venue_last5_win_rate",
            ]
        ],
        on=merge_cols,
        how="left",
    )

    merge_cols = ["match_date", "competition", "away_team"]
    df = df.merge(
        away_features[
            merge_cols
            + [
                "away_prev_matches",
                "away_last5_win_rate",
                "away_last5_avg_margin",
                "away_last5_market_surprise",
                "away_last5_points_for",
                "away_last5_points_against",
                "away_last5_total_surprise",
                "away_venue_last5_win_rate",
            ]
        ],
        on=merge_cols,
        how="left",
    )

    df["competition_prior_total_avg"] = df.groupby("competition")["total_line"].transform(lambda s: s.shift(1).expanding().mean())
    df["competition_prior_total_avg"] = df["competition_prior_total_avg"].fillna(df["total_line"].median())
    df["total_line_vs_comp_avg"] = df["total_line"] - df["competition_prior_total_avg"]

    df["market_surprise_diff"] = df["home_last5_market_surprise"] - df["away_last5_market_surprise"]
    df["margin_diff"] = df["home_last5_avg_margin"] - df["away_last5_avg_margin"]
    df["win_rate_diff"] = df["home_last5_win_rate"] - df["away_last5_win_rate"]
    df["combined_total_surprise"] = df["home_last5_total_surprise"] + df["away_last5_total_surprise"]
    df["combined_attack"] = df["home_last5_points_for"] + df["away_last5_points_for"]
    df["combined_defense_leak"] = df["home_last5_points_against"] + df["away_last5_points_against"]
    return df


def summarise(rule: str, market: str, train_profit: pd.Series, test_profit: pd.Series) -> RuleResult:
    train_bets = int((train_profit != 0).sum())
    test_bets = int((test_profit != 0).sum())
    train_total = float(train_profit.sum())
    test_total = float(test_profit.sum())
    return RuleResult(
        market=market,
        rule=rule,
        train_bets=train_bets,
        train_profit=round(train_total, 4),
        train_roi=round((train_total / train_bets) * 100.0, 2) if train_bets else 0.0,
        test_bets=test_bets,
        test_profit=round(test_total, 4),
        test_roi=round((test_total / test_bets) * 100.0, 2) if test_bets else 0.0,
    )


def eval_moneyline(frame: pd.DataFrame, side: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    if side == "HOME":
        won = frame["home_score"] > frame["away_score"]
        odds = frame["home_moneyline_decimal"]
    else:
        won = frame["away_score"] > frame["home_score"]
        odds = frame["away_moneyline_decimal"]
    return pd.Series([profit_from_decimal(odd, result) for odd, result in zip(odds, won, strict=False)])


def eval_total(frame: pd.DataFrame, side: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    totals = frame["home_score"] + frame["away_score"]
    if side == "OVER":
        won = totals > frame["total_line"]
        odds = frame["over_odds_decimal"]
    else:
        won = totals < frame["total_line"]
        odds = frame["under_odds_decimal"]
    return pd.Series([profit_from_decimal(odd, result) for odd, result in zip(odds, won, strict=False)])


def run_search(df: pd.DataFrame) -> pd.DataFrame:
    min_history = 3
    usable = df.loc[(df["home_prev_matches"] >= min_history) & (df["away_prev_matches"] >= min_history)].copy()
    usable = usable.sort_values("match_date").reset_index(drop=True)
    split_idx = int(len(usable) * 0.7)
    train = usable.iloc[:split_idx].copy()
    test = usable.iloc[split_idx:].copy()

    results: list[RuleResult] = []

    for side in ["HOME", "AWAY"]:
        odds_col = "home_moneyline_decimal" if side == "HOME" else "away_moneyline_decimal"
        direction = 1.0 if side == "HOME" else -1.0
        for surprise_threshold in [0.03, 0.05, 0.08]:
            for margin_threshold in [2.0, 4.0, 6.0]:
                for low_odds, high_odds in [(1.6, 2.4), (1.8, 2.8), (2.0, 3.5)]:
                    train_mask = (
                        (train[odds_col] >= low_odds)
                        & (train[odds_col] <= high_odds)
                        & ((direction * train["market_surprise_diff"]) >= surprise_threshold)
                        & ((direction * train["margin_diff"]) >= margin_threshold)
                    )
                    test_mask = (
                        (test[odds_col] >= low_odds)
                        & (test[odds_col] <= high_odds)
                        & ((direction * test["market_surprise_diff"]) >= surprise_threshold)
                        & ((direction * test["margin_diff"]) >= margin_threshold)
                    )
                    results.append(
                        summarise(
                            (
                                f"{side} ML odds {low_odds:.1f}-{high_odds:.1f} "
                                f"surprise>={surprise_threshold:.2f} margin>={margin_threshold:.1f}"
                            ),
                            "moneyline",
                            eval_moneyline(train.loc[train_mask], side),
                            eval_moneyline(test.loc[test_mask], side),
                        )
                    )

    totals = usable.dropna(subset=["total_line", "over_odds_decimal", "under_odds_decimal"]).copy()
    split_idx = int(len(totals) * 0.7)
    train_t = totals.iloc[:split_idx].copy()
    test_t = totals.iloc[split_idx:].copy()
    for side in ["OVER", "UNDER"]:
        for surprise_threshold in [2.0, 4.0, 6.0]:
            for relative_line in [-4.0, -2.0, 0.0, 2.0, 4.0]:
                if side == "OVER":
                    train_mask = (
                        (train_t["combined_total_surprise"] >= surprise_threshold)
                        & (train_t["total_line_vs_comp_avg"] <= relative_line)
                    )
                    test_mask = (
                        (test_t["combined_total_surprise"] >= surprise_threshold)
                        & (test_t["total_line_vs_comp_avg"] <= relative_line)
                    )
                else:
                    train_mask = (
                        (train_t["combined_total_surprise"] <= -surprise_threshold)
                        & (train_t["total_line_vs_comp_avg"] >= relative_line)
                    )
                    test_mask = (
                        (test_t["combined_total_surprise"] <= -surprise_threshold)
                        & (test_t["total_line_vs_comp_avg"] >= relative_line)
                    )

                results.append(
                    summarise(
                        (
                            f"{side} total combined_surprise "
                            f"{'>=' if side == 'OVER' else '<='}{surprise_threshold:.1f} "
                            f"line_vs_comp {'<=' if side == 'OVER' else '>='}{relative_line:.1f}"
                        ),
                        "total",
                        eval_total(train_t.loc[train_mask], side),
                        eval_total(test_t.loc[test_mask], side),
                    )
                )

    result_frame = pd.DataFrame([result.__dict__ for result in results])
    result_frame = result_frame.loc[(result_frame["train_bets"] >= 12) & (result_frame["test_bets"] >= 8)]
    result_frame = result_frame.sort_values(["test_roi", "train_roi", "test_profit"], ascending=False)
    return result_frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward rugby model using rolling pre-match features.")
    parser.add_argument("--csv", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    frames = [pd.read_csv(path) for path in args.csv]
    combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["event_url"])
    featured = build_features(combined)
    results = run_search(featured)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_path, index=False)

    robust = results.loc[(results["train_roi"] > 0) & (results["test_roi"] > 0)]
    print(f"Rows analysed: {len(featured)}")
    print(f"Candidate rules saved: {len(results)}")
    if robust.empty:
        print("No rules were positive in both train and test.")
        print(results.head(12).to_string(index=False))
    else:
        print("Best rules positive in both train and test:")
        print(robust.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
