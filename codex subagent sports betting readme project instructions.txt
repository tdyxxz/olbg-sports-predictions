# Sports Betting Subagent System

## Overview

This project implements a modular sports betting prediction system using a multi-agent architecture.

The system is designed to:
- Ingest sports data
- Generate predictive features
- Build probabilistic models
- Evaluate performance via backtesting
- Apply strict risk filtering
- Output only high-confidence betting opportunities

The system prioritizes:
- Selectivity over volume
- Risk control over prediction accuracy
- Long-term ROI over short-term wins

---

## Architecture

The system consists of the following agents:

### 1. Data Agent
- Inputs: raw sports data (odds, stats, injuries, etc.)
- Outputs: cleaned and structured dataset

### 2. Feature Engineering Agent
- Converts raw data into predictive signals
- Examples:
  - rolling averages
  - efficiency metrics
  - fatigue indicators
  - line movement signals

### 3. Modeling Agent
- Produces probability estimates
- Combines multiple approaches:
  - statistical models
  - heuristics
- Outputs:
  - win probabilities
  - model agreement metrics

### 4. Backtesting Agent
- Evaluates historical performance
- Metrics:
  - ROI
  - win rate
  - drawdown
  - closing line value (CLV)

### 5. Risk Filter Agent
- Filters out weak or uncertain bets
- Enforces:
  - minimum edge threshold
  - confidence thresholds
  - volatility constraints

### 6. Strategy Agent
- Converts predictions into betting recommendations
- Includes:
  - market selection
  - bet type
  - estimated edge
  - confidence score

### 7. No-Bet Agent
- Acts as a final gatekeeper
- Rejects uncertain or low-quality opportunities

---

## Running the System

### Input Requirements
- Sports data including:
  - teams
  - recent performance
  - odds
  - injuries
  - contextual factors

### Execution Flow
1. Data ingestion
2. Feature engineering
3. Modeling
4. Backtesting
5. Risk filtering
6. Strategy generation
7. Final decision (bet or no bet)

---

## Output Format

The system outputs:

- Approved bets:
  - market
  - selection
  - confidence
  - estimated edge
  - rationale

OR

- NO BET if no qualifying opportunities exist

---

## Key Principles

- The system is designed to reject most opportunities
- Only high-confidence, high-edge bets are selected
- Consistency and discipline are critical
- Overtrading is avoided
- Risk management is prioritized over prediction frequency

---

## Notes

- This system is modular and can be extended with:
  - real-time data APIs
  - advanced machine learning models
  - portfolio optimization layers
  - correlation-aware betting

- Performance depends heavily on:
  - data quality
  - feature engineering
  - strict adherence to filtering rules