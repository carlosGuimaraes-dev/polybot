---
description: "Use when: touching trading risk logic, config.py thresholds, Kelly sizing, paper vs live DB, broker execution, or anything that places orders or writes trades. Enforces evidence-based parameter changes and production-money safety."
name: "Trading Risk Safety"
applyTo: ["config.py", "db.py", "main.py", "daemon.py", "broker/**", "signals/edge_calculator.py"]
---

# Trading Risk Safety

This bot trades real USDC on-chain. A "small refactor" here can lose money. Follow these rules exactly.

## Parameter changes (`config.py`)

- **Never change a risk/threshold parameter without citing evidence from resolved trades.** Every value in `config.py` was tuned from resolved-trade history and has a comment explaining why. Before proposing a change, query the DB (`trades` table) or ask the user for the win-rate/ROI data that justifies it, and cite the numbers in your reasoning.
- Loosening (lower `MIN_EDGE`, higher `KELLY_FRACTION`/`MAX_TRADE_USDC`, wider NO-entry price range, lower ensemble-std gates) requires stronger evidence than tightening. State explicitly whether you are loosening or tightening.
- Never remove or bypass an entry gate (`neighbor_check`, `consistency_checker`, `confidence_tier`, order-book depth check, opportunistic-scan guards) to "let a trade through". If a trade is blocked, that is the system working.

## Paper vs live money

- `db.py` switches `DB_PATH` between `paper_trades.db` and `live_trades.db`. **Check which mode is active before any write path you touch.** Treat `live_trades.db` as production money: no schema changes, no destructive queries, no "quick fixes" without explicit user confirmation.
- Never add code that auto-flips the live/paper mode or sets live mode as a side effect of an import or module-level call.
- Live order paths (`broker/live_broker.py`) require explicit human confirmation before any change to order construction, size, or side is tested against the real CLOB.

## Safe execution

- When experimenting, always run with `--dry-run` first (`python main.py --scan --dry-run`).
- Do not run two `--scan`/`--backfill` instances concurrently; they contend on `polymarket_bot.lock` (fcntl).
- Do not delete `polymarket_bot.lock`, `paper_trades.db-shm`/`-wal`, or move/copy the DB while the daemon may be running.
- Never read or print `.env` values into logs, code, or chat. Credentials live only in the environment.

## Justifying changes

When you modify anything under `config.py` or `broker/`, your summary must answer:

1. Which parameters/paths changed, and direction (loosening/tightening)?
2. What resolved-trade evidence supports it (win rate, ROI, trade count)?
3. How was it validated (dry-run output, paper DB, no live writes)?
