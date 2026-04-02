from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def safe_float(value: str, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def safe_int(value: str, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def first_present(row: Dict[str, str], keys: List[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def decimal_odds_to_implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        return 0.0
    return 1.0 / decimal_odds


def parse_finish_position(value: str) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in {"MC", "WD", "DQ"}:
        return 999
    if text.startswith("T"):
        text = text[1:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def derive_top10_result(row: Dict[str, str]) -> int:
    explicit = first_present(
        row,
        [
            "top10_result",
            "top_10_result",
            "result_top10",
            "bet_result",
            "outcome",
            "won",
        ],
    ).strip()
    if explicit:
        lowered = explicit.lower()
        if lowered in {"1", "true", "win", "won", "yes", "y"}:
            return 1
        if lowered in {"0", "false", "loss", "lost", "no", "n"}:
            return 0
        return 1 if safe_int(explicit, 0) == 1 else 0
    finish_position = parse_finish_position(first_present(row, ["finish_position", "finish_pos", "pos", "finish"]))
    if finish_position is None:
        return 0
    return 1 if finish_position <= 10 else 0


def parse_event_date(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d")


@dataclass
class ModelConfig:
    weight_recent_top10_rate: float = 2.0
    weight_recent_made_cut_rate: float = 1.2
    weight_last5_top10_rate: float = 1.1
    weight_last5_made_cut_rate: float = 0.8
    weight_sg_approach: float = 1.6
    weight_sg_t2g: float = 1.4
    weight_sg_total: float = 1.0
    weight_sg_putting: float = 0.35
    weight_course_history_top10_rate: float = 0.85
    weight_course_fit_score: float = 1.2
    weight_weather_fit_score: float = 0.35
    weight_world_rank_score: float = 0.9
    intercept: float = -0.25
    score_scale: float = 4.2
    min_edge: float = 0.04
    min_model_prob: float = 0.10
    min_odds: float = 2.0
    max_odds: float = 8.0
    max_bets_per_event: int = 2


def world_rank_to_score(world_rank: int) -> float:
    if world_rank <= 0:
        return 0.0
    return clamp(1.0 - ((min(world_rank, 200) - 1) / 199.0), 0.0, 1.0)


def sg_to_unit(value: float) -> float:
    return clamp((value + 2.0) / 4.0, 0.0, 1.0)


def avg_finish_to_score(avg_finish: float, field_size: int) -> float:
    if avg_finish <= 0 or field_size <= 0:
        return 0.0
    return clamp(1.0 - ((avg_finish - 1.0) / max(field_size - 1.0, 1.0)), 0.0, 1.0)


def compute_feature_score(row: Dict[str, str], config: ModelConfig) -> float:
    field_size = safe_int(row.get("field_size", ""), 156)
    last5_top10_rate = clamp(safe_float(row.get("last5_top10_count", "")) / 5.0, 0.0, 1.0)
    last5_made_cut_rate = clamp(safe_float(row.get("last5_made_cuts", "")) / 5.0, 0.0, 1.0)
    course_history_top10_rate = clamp(safe_float(row.get("course_history_top10_rate", "")), 0.0, 1.0)
    course_fit_score = clamp(safe_float(row.get("course_fit_score", "")), 0.0, 1.0)
    weather_fit_score = clamp(safe_float(row.get("weather_fit_score", "")), 0.0, 1.0)
    avg_finish_score = avg_finish_to_score(safe_float(row.get("course_history_avg_finish", "")), field_size)
    world_rank_score = world_rank_to_score(safe_int(row.get("world_rank", "")))

    score = 0.0
    score += config.weight_recent_top10_rate * clamp(safe_float(row.get("recent_top10_rate_12m", "")), 0.0, 1.0)
    score += config.weight_recent_made_cut_rate * clamp(safe_float(row.get("recent_made_cut_rate_12m", "")), 0.0, 1.0)
    score += config.weight_last5_top10_rate * last5_top10_rate
    score += config.weight_last5_made_cut_rate * last5_made_cut_rate
    score += config.weight_sg_approach * sg_to_unit(safe_float(row.get("recent_sg_approach", "")))
    score += config.weight_sg_t2g * sg_to_unit(safe_float(row.get("recent_sg_t2g", "")))
    score += config.weight_sg_total * sg_to_unit(safe_float(row.get("recent_sg_total", "")))
    score += config.weight_sg_putting * sg_to_unit(safe_float(row.get("recent_sg_putting", "")))
    score += config.weight_course_history_top10_rate * ((course_history_top10_rate * 0.75) + (avg_finish_score * 0.25))
    score += config.weight_course_fit_score * course_fit_score
    score += config.weight_weather_fit_score * weather_fit_score
    score += config.weight_world_rank_score * world_rank_score
    return score


def get_open_odds(row: Dict[str, str]) -> float:
    return safe_float(
        first_present(
            row,
            [
                "top10_odds_open",
                "top_10_odds_open",
                "open_odds",
                "opening_odds",
                "odds_open",
                "open",
            ],
        )
    )


def get_close_odds(row: Dict[str, str]) -> float:
    return safe_float(
        first_present(
            row,
            [
                "top10_odds_close",
                "top_10_odds_close",
                "close_odds",
                "closing_odds",
                "odds_close",
                "close",
            ],
        )
    )


def get_direct_model_prob(row: Dict[str, str]) -> Optional[float]:
    text = first_present(
        row,
        [
            "model_prob",
            "top10_model_prob",
            "top_10_model_prob",
            "pred_top10",
            "pred_top_10",
            "dg_top10_prob",
            "datagolf_top10_prob",
            "top_10",
            "top10_prob",
        ],
    )
    if not text:
        return None
    value = safe_float(text, -1.0)
    if value < 0:
        return None
    if value > 1.0:
        value = value / 100.0
    return clamp(value, 0.001, 0.999)


def total_feature_weight(config: ModelConfig) -> float:
    return (
        config.weight_recent_top10_rate
        + config.weight_recent_made_cut_rate
        + config.weight_last5_top10_rate
        + config.weight_last5_made_cut_rate
        + config.weight_sg_approach
        + config.weight_sg_t2g
        + config.weight_sg_total
        + config.weight_sg_putting
        + config.weight_course_history_top10_rate
        + config.weight_course_fit_score
        + config.weight_weather_fit_score
        + config.weight_world_rank_score
    )


def probability_from_score(score: float, field_size: int, config: ModelConfig) -> float:
    field_size = max(field_size, 60)
    baseline_probability = clamp(10.0 / field_size, 0.03, 0.25)
    baseline_logit = math.log(baseline_probability / (1.0 - baseline_probability))
    normalized_score = clamp(score / total_feature_weight(config), 0.0, 1.0)
    centered_score = normalized_score - 0.5
    return clamp(sigmoid(baseline_logit + config.intercept + (centered_score * config.score_scale)), 0.001, 0.999)


def confidence_label(edge: float) -> str:
    if edge >= 0.08:
        return "HIGH"
    if edge >= 0.05:
        return "MEDIUM"
    return "LOW"


def load_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    rows.sort(key=lambda row: (row.get("event_date", ""), row.get("event_id", ""), row.get("player_name", "")))
    return rows


def group_rows_by_event(rows: Iterable[Dict[str, str]]) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for row in rows:
        key = (row.get("event_date", ""), row.get("event_id", ""))
        grouped.setdefault(key, []).append(row)
    return grouped


def evaluate_rows(rows: List[Dict[str, str]], config: ModelConfig) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    grouped = group_rows_by_event(rows)
    bets: List[Dict[str, object]] = []

    for (_, _), event_rows in grouped.items():
        scored_rows = []
        for row in event_rows:
            open_odds = get_open_odds(row)
            if open_odds <= 1.0:
                continue
            feature_score = compute_feature_score(row, config)
            field_size = safe_int(row.get("field_size", ""), 156)
            direct_model_prob = get_direct_model_prob(row)
            model_prob = direct_model_prob if direct_model_prob is not None else probability_from_score(feature_score, field_size, config)
            implied_prob = decimal_odds_to_implied_prob(open_odds)
            edge = model_prob - implied_prob
            scored_rows.append(
                {
                    "row": row,
                    "feature_score": feature_score,
                    "model_prob": model_prob,
                    "implied_prob": implied_prob,
                    "edge": edge,
                }
            )

        qualified = [
            item for item in scored_rows
            if get_open_odds(item["row"]) >= config.min_odds
            and get_open_odds(item["row"]) <= config.max_odds
            and item["model_prob"] >= config.min_model_prob
            and item["edge"] >= config.min_edge
        ]
        qualified.sort(key=lambda item: (item["edge"], item["model_prob"]), reverse=True)

        for item in qualified[: config.max_bets_per_event]:
            row = item["row"]
            open_odds = get_open_odds(row)
            close_odds = get_close_odds(row)
            result = derive_top10_result(row)
            profit = (open_odds - 1.0) if result == 1 else -1.0
            clv_edge = None
            if close_odds > 1.0:
                clv_edge = decimal_odds_to_implied_prob(close_odds) - item["implied_prob"]

            bets.append(
                {
                    "event_date": row.get("event_date", ""),
                    "event_id": row.get("event_id", ""),
                    "event_name": row.get("event_name", ""),
                    "player_name": row.get("player_name", ""),
                    "book": row.get("book", ""),
                    "open_odds": round(open_odds, 4),
                    "close_odds": round(close_odds, 4) if close_odds > 1.0 else "",
                    "model_prob": round(item["model_prob"], 4),
                    "implied_prob": round(item["implied_prob"], 4),
                    "edge": round(item["edge"], 4),
                    "feature_score": round(item["feature_score"], 4),
                    "confidence": confidence_label(item["edge"]),
                    "result": result,
                    "profit": round(profit, 4),
                    "clv_edge": round(clv_edge, 4) if clv_edge is not None else "",
                }
            )

    summary = summarize_bets(bets)
    return bets, summary


def summarize_bets(bets: List[Dict[str, object]]) -> Dict[str, object]:
    total_bets = len(bets)
    total_profit = round(sum(safe_float(bet.get("profit", 0.0)) for bet in bets), 4)
    wins = sum(1 for bet in bets if safe_int(bet.get("result", 0)) == 1)
    stake = float(total_bets)
    roi = round(total_profit / stake, 4) if stake else 0.0
    hit_rate = round(wins / total_bets, 4) if total_bets else 0.0
    avg_open_odds = round(statistics.mean(safe_float(bet.get("open_odds", 0.0)) for bet in bets), 4) if bets else 0.0
    avg_model_prob = round(statistics.mean(safe_float(bet.get("model_prob", 0.0)) for bet in bets), 4) if bets else 0.0
    avg_implied_prob = round(statistics.mean(safe_float(bet.get("implied_prob", 0.0)) for bet in bets), 4) if bets else 0.0
    avg_edge = round(statistics.mean(safe_float(bet.get("edge", 0.0)) for bet in bets), 4) if bets else 0.0

    clv_values = [safe_float(bet.get("clv_edge", "")) for bet in bets if str(bet.get("clv_edge", "")).strip() != ""]
    avg_clv_edge = round(statistics.mean(clv_values), 4) if clv_values else 0.0

    by_confidence: Dict[str, Dict[str, float]] = {}
    for label in ("LOW", "MEDIUM", "HIGH"):
        label_bets = [bet for bet in bets if bet.get("confidence") == label]
        if not label_bets:
            continue
        label_profit = sum(safe_float(bet.get("profit", 0.0)) for bet in label_bets)
        by_confidence[label] = {
            "bets": len(label_bets),
            "wins": sum(1 for bet in label_bets if safe_int(bet.get("result", 0)) == 1),
            "roi": round(label_profit / len(label_bets), 4),
        }

    return {
        "bets": total_bets,
        "wins": wins,
        "hit_rate": hit_rate,
        "total_profit": total_profit,
        "roi": roi,
        "avg_open_odds": avg_open_odds,
        "avg_model_prob": avg_model_prob,
        "avg_implied_prob": avg_implied_prob,
        "avg_edge": avg_edge,
        "avg_clv_edge": avg_clv_edge,
        "by_confidence": by_confidence,
    }


def write_bets_csv(bets: List[Dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_date",
        "event_id",
        "event_name",
        "player_name",
        "book",
        "open_odds",
        "close_odds",
        "model_prob",
        "implied_prob",
        "edge",
        "feature_score",
        "confidence",
        "result",
        "profit",
        "clv_edge",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bets)


def write_report_json(report: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)


def optimize_config(rows: List[Dict[str, str]], base_config: ModelConfig) -> Tuple[ModelConfig, Dict[str, object]]:
    best_config = base_config
    best_summary: Dict[str, object] = {"roi": float("-inf"), "bets": 0}

    intercept_grid = [-0.6, -0.4, -0.25, -0.1, 0.0]
    scale_grid = [3.2, 3.8, 4.2, 4.8, 5.4]
    min_edge_grid = [0.03, 0.04, 0.05, 0.06]
    min_prob_grid = [0.08, 0.10, 0.12]
    max_odds_grid = [6.0, 8.0, 10.0]
    max_bets_grid = [1, 2, 3]

    for intercept in intercept_grid:
        for score_scale in scale_grid:
            for min_edge in min_edge_grid:
                for min_prob in min_prob_grid:
                    for max_odds in max_odds_grid:
                        for max_bets in max_bets_grid:
                            candidate = ModelConfig(
                                weight_recent_top10_rate=base_config.weight_recent_top10_rate,
                                weight_recent_made_cut_rate=base_config.weight_recent_made_cut_rate,
                                weight_last5_top10_rate=base_config.weight_last5_top10_rate,
                                weight_last5_made_cut_rate=base_config.weight_last5_made_cut_rate,
                                weight_sg_approach=base_config.weight_sg_approach,
                                weight_sg_t2g=base_config.weight_sg_t2g,
                                weight_sg_total=base_config.weight_sg_total,
                                weight_sg_putting=base_config.weight_sg_putting,
                                weight_course_history_top10_rate=base_config.weight_course_history_top10_rate,
                                weight_course_fit_score=base_config.weight_course_fit_score,
                                weight_weather_fit_score=base_config.weight_weather_fit_score,
                                weight_world_rank_score=base_config.weight_world_rank_score,
                                intercept=intercept,
                                score_scale=score_scale,
                                min_edge=min_edge,
                                min_model_prob=min_prob,
                                min_odds=base_config.min_odds,
                                max_odds=max_odds,
                                max_bets_per_event=max_bets,
                            )
                            _, summary = evaluate_rows(rows, candidate)
                            if summary["bets"] < 25:
                                continue
                            score = (summary["roi"], summary["avg_clv_edge"], -summary["avg_open_odds"])
                            best_score = (
                                best_summary.get("roi", float("-inf")),
                                best_summary.get("avg_clv_edge", float("-inf")),
                                -best_summary.get("avg_open_odds", float("inf")),
                            )
                            if score > best_score:
                                best_config = candidate
                                best_summary = summary
    return best_config, best_summary


def build_report(config: ModelConfig, summary: Dict[str, object], bets_output: Optional[Path]) -> Dict[str, object]:
    return {
        "strategy": "golf_top10_profitability",
        "config": {
            "intercept": config.intercept,
            "score_scale": config.score_scale,
            "min_edge": config.min_edge,
            "min_model_prob": config.min_model_prob,
            "min_odds": config.min_odds,
            "max_odds": config.max_odds,
            "max_bets_per_event": config.max_bets_per_event,
        },
        "summary": summary,
        "bets_output": str(bets_output) if bets_output else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest golf top-10 betting selections from a historical CSV.")
    parser.add_argument("--input", required=True, help="Input CSV path.")
    parser.add_argument("--output", required=True, help="JSON report output path.")
    parser.add_argument("--bets-output", help="Optional CSV path for individual bets.")
    parser.add_argument("--optimize", action="store_true", help="Run a threshold grid search before the final backtest.")
    parser.add_argument("--intercept", type=float, help="Override the model intercept.")
    parser.add_argument("--score-scale", type=float, help="Override the model score scale.")
    parser.add_argument("--min-edge", type=float, help="Override the minimum probability edge required.")
    parser.add_argument("--min-model-prob", type=float, help="Override the minimum model probability required.")
    parser.add_argument("--min-odds", type=float, help="Override the minimum decimal odds allowed.")
    parser.add_argument("--max-odds", type=float, help="Override the maximum decimal odds allowed.")
    parser.add_argument("--max-bets-per-event", type=int, help="Override the max number of bets per event.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    bets_output = Path(args.bets_output) if args.bets_output else None

    rows = load_rows(input_path)
    config = ModelConfig()

    if args.intercept is not None:
        config.intercept = args.intercept
    if args.score_scale is not None:
        config.score_scale = args.score_scale
    if args.min_edge is not None:
        config.min_edge = args.min_edge
    if args.min_model_prob is not None:
        config.min_model_prob = args.min_model_prob
    if args.min_odds is not None:
        config.min_odds = args.min_odds
    if args.max_odds is not None:
        config.max_odds = args.max_odds
    if args.max_bets_per_event is not None:
        config.max_bets_per_event = args.max_bets_per_event

    optimization_summary = None
    if args.optimize:
        config, optimization_summary = optimize_config(rows, config)

    bets, summary = evaluate_rows(rows, config)

    if bets_output:
        write_bets_csv(bets, bets_output)

    report = build_report(config, summary, bets_output)
    if optimization_summary is not None:
        report["optimization_summary"] = optimization_summary

    write_report_json(report, output_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
