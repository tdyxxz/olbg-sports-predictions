# Basketball OLBG

NBA live runner and cache warmer built with the same runtime-first pattern as baseball.

## Sources

- ESPN NBA scoreboard API for daily games, odds, records, and team leaders
- ESPN team schedule API for recent form
- OddsPortal historical NBA moneylines via the local `OddsHarvester` checkout in `RUGBY UNION OLBG\_external\OddsHarvester-master`

## Commands

```powershell
python .\scripts\warm_nba_live_cache.py --date 2026-04-02
python .\scripts\predict_nba_card.py --date 2026-04-02 --fast
python .\scripts\predict_nba_card.py --date 2026-04-02
python .\scripts\predict_nba_card.py --date 2026-04-02 --config .\config\shadow_favorites_v1.json --fast
python .\scripts\run_daily_basketball_cycle.py --date 2026-04-02 --fast
python .\scripts\fetch_historical_nba_odds.py --season 2025-2026 --max-pages 5
python .\scripts\grow_nba_historical_sample.py --season 2025-2026 --target-pages 5
python .\scripts\merge_nba_historical_odds.py
python .\scripts\build_nba_feature_dataset.py
python .\scripts\backtest_nba_moneyline_model.py
```

## Notes

- Public writeups avoid any model or process language.
- `--fast` writes JSON only for internal iteration.
- Live cache artifacts are stored under `data\cache`.
- Daily settlement is tracked by `scripts\track_saved_pick_performance.py`.
- The daily cycle runs the baseline and the current basketball shadow strategy.
- Historical odds fetches are intentionally isolated from the live path because they are much slower than the ESPN live runner.
- The dataset builder and backtest only read local cached files after the fetch step has completed.
- Historical NBA collection should grow through deduped page snapshots rather than rerunning one giant scrape blindly.
