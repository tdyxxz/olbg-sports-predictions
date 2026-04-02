# Cricket OLBG

Fast cricket workflow built around the current OLBG board.

## Sources

- OLBG cricket betting tips page for the live candidate board, featured market, odds, and board consensus

## Commands

```powershell
python .\scripts\run_daily_cricket_cycle.py --date 2026-04-02 --fast
python .\scripts\predict_cricket_card.py --date 2026-04-02 --fast
python .\scripts\track_saved_pick_performance.py
python .\scripts\fetch_historical_cricket_sample.py --target-size 40
python .\scripts\backtest_cricket_moneyline_model.py
python ..\scripts\fetch_olbg_event_board.py --sport cricket
```

## Notes

- OLBG is the board gate for cricket.
- The first cricket version is intentionally runtime-first and board-driven.
- Public writeups avoid any model or process language.
- Settlement tracking is built from saved prediction files and OLBG event pages; unresolved picks stay open until a winner can be detected.
- Historical cricket sampling is separate from the live runner so the OLBG daily flow stays fast.
