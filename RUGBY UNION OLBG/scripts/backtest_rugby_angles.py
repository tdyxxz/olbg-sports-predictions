import argparse
from dataclasses import dataclass

import pandas as pd


@dataclass
class StrategyResult:
    market: str
    rule: str
    train_bets: int
    train_profit: float
    train_roi: float
    test_bets: int
    test_profit: float
    test_roi: float


def profit_from_decimal_odds(odds: float, won: bool) -> float:
    return (odds - 1.0) if won else -1.0


def evaluate_moneyline(frame: pd.DataFrame, selection: str) -> pd.Series:
    if selection == "HOME":
        won = frame["home_score"] > frame["away_score"]
        odds = frame["home_moneyline_decimal"]
    else:
        won = frame["away_score"] > frame["home_score"]
        odds = frame["away_moneyline_decimal"]
    return pd.Series(
        [profit_from_decimal_odds(odd, result) for odd, result in zip(odds, won, strict=False)],
        index=frame.index,
    )


def evaluate_handicap(frame: pd.DataFrame) -> pd.Series:
    def result(row):
        if pd.isna(row["handicap_team"]) or pd.isna(row["handicap_line"]) or pd.isna(row["handicap_odds_decimal"]):
            return 0.0
        if row["handicap_team"] == "HOME":
            covered = row["home_score"] + row["handicap_line"] > row["away_score"]
        else:
            covered = row["away_score"] + row["handicap_line"] > row["home_score"]
        return profit_from_decimal_odds(row["handicap_odds_decimal"], covered)

    return frame.apply(result, axis=1)


def evaluate_total(frame: pd.DataFrame, side: str) -> pd.Series:
    total_score = frame["home_score"] + frame["away_score"]
    if side == "UNDER":
        won = total_score < frame["total_line"]
        odds = frame["under_odds_decimal"]
    else:
        won = total_score > frame["total_line"]
        odds = frame["over_odds_decimal"]
    return pd.Series(
        [profit_from_decimal_odds(odd, result) for odd, result in zip(odds, won, strict=False)],
        index=frame.index,
    )


def summarise(rule_name: str, market: str, train_profit: pd.Series, test_profit: pd.Series) -> StrategyResult:
    train_bets = int((train_profit != 0).sum())
    test_bets = int((test_profit != 0).sum())
    train_total = float(train_profit.sum())
    test_total = float(test_profit.sum())
    return StrategyResult(
        market=market,
        rule=rule_name,
        train_bets=train_bets,
        train_profit=round(train_total, 4),
        train_roi=round((train_total / train_bets) * 100.0, 2) if train_bets else 0.0,
        test_bets=test_bets,
        test_profit=round(test_total, 4),
        test_roi=round((test_total / test_bets) * 100.0, 2) if test_bets else 0.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest simple rugby betting angles on scraped odds data.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--train-season", required=True)
    parser.add_argument("--test-season", required=True)
    args = parser.parse_args()

    frame = pd.read_csv(args.csv)
    frame["match_date"] = pd.to_datetime(frame["match_date"])

    train = frame.loc[frame["season"] == args.train_season].copy()
    test = frame.loc[frame["season"] == args.test_season].copy()

    results: list[StrategyResult] = []

    competitions = sorted(frame["competition"].dropna().unique())

    for competition in competitions + ["ALL"]:
        train_comp = train if competition == "ALL" else train.loc[train["competition"] == competition]
        test_comp = test if competition == "ALL" else test.loc[test["competition"] == competition]

        if len(train_comp) < 20 or len(test_comp) < 20:
            continue

        for side in ["HOME", "AWAY"]:
            odds_col = "home_moneyline_decimal" if side == "HOME" else "away_moneyline_decimal"
            for low in [1.8, 2.0, 2.2, 2.5]:
                for high in [2.5, 3.0, 3.5, 4.0]:
                    if high <= low:
                        continue
                    train_mask = (train_comp[odds_col] >= low) & (train_comp[odds_col] < high)
                    test_mask = (test_comp[odds_col] >= low) & (test_comp[odds_col] < high)
                    train_profit = evaluate_moneyline(train_comp.loc[train_mask], side)
                    test_profit = evaluate_moneyline(test_comp.loc[test_mask], side)
                    results.append(
                        summarise(
                            f"{competition} {side} moneyline {low:.1f}-{high:.1f}",
                            "moneyline",
                            train_profit,
                            test_profit,
                        )
                    )

        valid_train_h = train_comp.dropna(subset=["handicap_team", "handicap_line", "handicap_odds_decimal"])
        valid_test_h = test_comp.dropna(subset=["handicap_team", "handicap_line", "handicap_odds_decimal"])
        if len(valid_train_h) >= 20 and len(valid_test_h) >= 20:
            for low in [3.5, 4.5, 5.5]:
                for high in [7.5, 8.5, 9.5, 10.5]:
                    if high <= low:
                        continue
                    train_mask = (valid_train_h["handicap_line"] >= low) & (valid_train_h["handicap_line"] <= high)
                    test_mask = (valid_test_h["handicap_line"] >= low) & (valid_test_h["handicap_line"] <= high)
                    train_profit = evaluate_handicap(valid_train_h.loc[train_mask])
                    test_profit = evaluate_handicap(valid_test_h.loc[test_mask])
                    results.append(
                        summarise(
                            f"{competition} underdog handicap +{low:.1f} to +{high:.1f}",
                            "handicap",
                            train_profit,
                            test_profit,
                        )
                    )

        valid_train_t = train_comp.dropna(subset=["total_line", "over_odds_decimal", "under_odds_decimal"])
        valid_test_t = test_comp.dropna(subset=["total_line", "over_odds_decimal", "under_odds_decimal"])
        if len(valid_train_t) >= 20 and len(valid_test_t) >= 20:
            for side in ["UNDER", "OVER"]:
                thresholds = [44.5, 46.5, 48.5, 50.5, 52.5, 54.5]
                for threshold in thresholds:
                    if side == "UNDER":
                        train_mask = valid_train_t["total_line"] >= threshold
                        test_mask = valid_test_t["total_line"] >= threshold
                    else:
                        train_mask = valid_train_t["total_line"] <= threshold
                        test_mask = valid_test_t["total_line"] <= threshold
                    train_profit = evaluate_total(valid_train_t.loc[train_mask], side)
                    test_profit = evaluate_total(valid_test_t.loc[test_mask], side)
                    results.append(
                        summarise(
                            f"{competition} {side} total threshold {threshold:.1f}",
                            "total",
                            train_profit,
                            test_profit,
                        )
                    )

    results_frame = pd.DataFrame([result.__dict__ for result in results])
    results_frame = results_frame.loc[(results_frame["train_bets"] >= 15) & (results_frame["test_bets"] >= 15)]
    results_frame = results_frame.sort_values(["test_roi", "test_profit", "train_roi"], ascending=False)

    if results_frame.empty:
        raise SystemExit("No strategy candidates met the minimum bet thresholds.")

    print("Top out-of-sample rules")
    print(results_frame.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
