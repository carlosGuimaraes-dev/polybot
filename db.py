"""
SQLite schema and all database operations.
All reads/writes go through this module — no raw SQL elsewhere.
"""
import sqlite3
import os
import json
import logging
from datetime import datetime, date
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DB_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(_DB_DIR, "paper_trades.db")


def set_mode(mode: str):
    """Switch between 'paper' and 'live' databases. Call before any DB operations."""
    global DB_PATH
    if mode == "live":
        DB_PATH = os.path.join(_DB_DIR, "live_trades.db")
    else:
        DB_PATH = os.path.join(_DB_DIR, "paper_trades.db")


def get_mode() -> str:
    """Return current mode: 'live' or 'paper'."""
    return "live" if "live_trades" in DB_PATH else "paper"


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:  # Transaction management (commit/rollback)
            yield conn
    finally:
        conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    icao        TEXT PRIMARY KEY,
    city        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    timezone    TEXT NOT NULL,
    uses_fahrenheit INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'warming_up',  -- warming_up | ready
    history_days INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_obs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    icao        TEXT NOT NULL REFERENCES stations(icao),
    obs_date    TEXT NOT NULL,
    actual_high_c REAL NOT NULL,
    source      TEXT NOT NULL,   -- 'asos' | 'openmeteo_archive'
    fetched_at  TEXT NOT NULL,
    UNIQUE(icao, obs_date, source)
);

CREATE TABLE IF NOT EXISTS model_forecasts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    icao        TEXT NOT NULL REFERENCES stations(icao),
    target_date TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    predicted_high_c REAL NOT NULL,
    radiation_mj_m2 REAL,           -- shortwave radiation sum (solar energy)
    sunshine_duration_s REAL,       -- sunshine duration in seconds
    fetched_at  TEXT NOT NULL,
    UNIQUE(icao, target_date, model_name, fetched_at)
);

CREATE TABLE IF NOT EXISTS bias_corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    icao        TEXT NOT NULL REFERENCES stations(icao),
    model_name  TEXT NOT NULL,
    month       INTEGER NOT NULL,
    bias_c      REAL NOT NULL,   -- mean(actual - predicted)
    sample_count INTEGER NOT NULL,
    last_updated TEXT NOT NULL,
    UNIQUE(icao, model_name, month)
);

CREATE TABLE IF NOT EXISTS markets (
    market_id   TEXT PRIMARY KEY,   -- Polymarket conditionId
    city        TEXT NOT NULL,
    icao        TEXT NOT NULL,
    target_date TEXT NOT NULL,
    question    TEXT NOT NULL,
    bucket_lo   REAL,               -- lower bound (NULL = -inf)
    bucket_hi   REAL,               -- upper bound (NULL = +inf)
    bucket_unit TEXT NOT NULL,      -- 'F' or 'C'
    clob_token_yes TEXT NOT NULL,   -- CLOB token for YES outcome
    fetched_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        TEXT PRIMARY KEY,
    market_id       TEXT NOT NULL REFERENCES markets(market_id),
    city            TEXT NOT NULL,
    icao            TEXT NOT NULL,
    target_date     TEXT NOT NULL,
    bucket_lo       REAL,
    bucket_hi       REAL,
    bucket_unit     TEXT NOT NULL,
    direction       TEXT NOT NULL,   -- 'YES' | 'NO'
    entry_price     REAL NOT NULL,   -- actual CLOB ask (YES) or 1-bid (NO) at entry
    model_prob      REAL NOT NULL,
    market_prob     REAL NOT NULL,
    edge            REAL NOT NULL,
    ensemble_std    REAL NOT NULL,
    size_usdc       REAL NOT NULL,
    kelly_f         REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | void
    entry_time      TEXT NOT NULL,
    exit_price      REAL,
    actual_high_c   REAL,
    pnl             REAL,
    resolved_at     TEXT,
    notes           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    pnl_date            TEXT PRIMARY KEY,
    starting_bankroll   REAL NOT NULL,
    ending_bankroll     REAL NOT NULL,
    trades_placed       INTEGER NOT NULL DEFAULT 0,
    trades_resolved     INTEGER NOT NULL DEFAULT 0,
    win_count           INTEGER NOT NULL DEFAULT 0,
    loss_count          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bankroll (
    id      INTEGER PRIMARY KEY,
    balance REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    city        TEXT,
    icao        TEXT,
    message     TEXT NOT NULL,
    data_json   TEXT
);

CREATE TABLE IF NOT EXISTS climatology (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    icao         TEXT NOT NULL REFERENCES stations(icao),
    month        INTEGER NOT NULL,   -- 1–12
    mean_c       REAL NOT NULL,
    std_c        REAL NOT NULL,
    p10_c        REAL NOT NULL,
    p90_c        REAL NOT NULL,
    sample_years INTEGER NOT NULL,
    last_updated TEXT NOT NULL,
    UNIQUE(icao, month)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id   TEXT NOT NULL,
    scanned_at  TEXT NOT NULL,
    mid_price   REAL NOT NULL,
    model_prob  REAL,
    edge        REAL,
    token_id    TEXT
);

CREATE TABLE IF NOT EXISTS calibration_predictions (
    pred_id     TEXT PRIMARY KEY,
    market_id   TEXT NOT NULL,
    scanned_at  TEXT NOT NULL,
    model_prob  REAL NOT NULL,
    market_prob REAL NOT NULL,
    outcome     REAL,          -- 1.0 won / 0.0 lost / NULL = open
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS tsa_calibration (
    pred_id     TEXT PRIMARY KEY,
    market_id   TEXT NOT NULL,
    scanned_at  TEXT NOT NULL,
    model_prob  REAL NOT NULL,
    market_prob REAL NOT NULL,
    tsa_mean_m  REAL,
    tsa_std_m   REAL,
    hub_weather_flag INTEGER,
    outcome     REAL,          -- 1.0 won / 0.0 lost / NULL = open
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS kv_store (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_target_date ON trades(target_date);
CREATE INDEX IF NOT EXISTS idx_obs_icao_date ON historical_obs(icao, obs_date);
CREATE INDEX IF NOT EXISTS idx_forecasts_icao_date ON model_forecasts(icao, target_date, fetched_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_unique ON price_history(market_id, scanned_at);
CREATE INDEX IF NOT EXISTS idx_price_history_market_ts ON price_history(market_id, scanned_at);
"""


def init_db():
    with _conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO bankroll (id, balance) VALUES (1, ?)",
                     (1000.0,))
        # Add confidence_tier column if it doesn't exist yet (migration)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN confidence_tier TEXT DEFAULT 'unknown'")
        except Exception:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN target_date_end TEXT")
        except Exception:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE price_history ADD COLUMN token_id TEXT")
        except Exception:
            pass
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_unique ON price_history(market_id, scanned_at)")
        except Exception:
            pass
        # outcome_source: 'polymarket' | 'weather_fallback' — tracks how resolution was determined
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN outcome_source TEXT DEFAULT 'polymarket'")
        except Exception:
            pass
        # lead_time_days: days between fetch date and target date — used for bias conditioning
        try:
            conn.execute("ALTER TABLE model_forecasts ADD COLUMN lead_time_days INTEGER")
        except Exception:
            pass
        # market_type: 'temperature' | 'tsa' — distinguishes market types in reporting
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN market_type TEXT DEFAULT 'temperature'")
        except Exception:
            pass
        # hub_weather_flag: TSA-specific — True if 2+ major hubs had bad weather
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN hub_weather_flag INTEGER DEFAULT NULL")
        except Exception:
            pass
        # bankroll_fix_applied: one-time correction for the double-deduction bug on lost trades.
        # Old resolve_trade added pnl=-size to bankroll on "lost" but stake was already deducted
        # at entry, so every lost trade was double-counted. Restore once by adding back size for
        # all lost trades that were resolved before this fix.
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN bankroll_fix_applied INTEGER DEFAULT 0")
        except Exception:
            pass  # Column already exists
        # clob_token_yes: CLOB token for the YES outcome, needed by open_trade_atomic.
        # Added to the CREATE TABLE schema without a migration — pre-existing DBs
        # crashed with 'table trades has no column named clob_token_yes' at trade entry.
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN clob_token_yes TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # Column already exists
        fixed = conn.execute(
            "SELECT COUNT(*) as c FROM trades WHERE status='lost' AND bankroll_fix_applied=0"
        ).fetchone()["c"]
        if fixed > 0:
            rows = conn.execute(
                "SELECT trade_id, size_usdc FROM trades WHERE status='lost' AND bankroll_fix_applied=0"
            ).fetchall()
            total_correction = sum(r["size_usdc"] for r in rows)
            conn.execute("UPDATE bankroll SET balance = balance + ? WHERE id=1",
                         (total_correction,))
            conn.execute(
                "UPDATE trades SET bankroll_fix_applied=1 WHERE status='lost' AND bankroll_fix_applied=0"
            )
            logger.info("Bankroll double-deduction fix: restored $%.2f across %d lost trades",
                        total_correction, fixed)
    logger.info("DB initialised at %s", DB_PATH)


# ── Bankroll ──────────────────────────────────────────────────────────────────

def get_bankroll() -> float:
    with _conn() as conn:
        row = conn.execute("SELECT balance FROM bankroll WHERE id=1").fetchone()
        return row["balance"] if row else 1000.0


def adjust_bankroll(delta: float):
    with _conn() as conn:
        conn.execute("UPDATE bankroll SET balance = balance + ? WHERE id=1", (delta,))


def set_bankroll(balance: float):
    """Overwrite bankroll with an authoritative value (e.g. live CLOB sync)."""
    with _conn() as conn:
        conn.execute("UPDATE bankroll SET balance = ? WHERE id=1", (balance,))


# ── Stations ──────────────────────────────────────────────────────────────────

def upsert_station(icao, city, lat, lon, timezone, uses_fahrenheit):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO stations (icao, city, lat, lon, timezone, uses_fahrenheit,
                                  status, history_days, created_at)
            VALUES (?,?,?,?,?,?, 'warming_up', 0, ?)
            ON CONFLICT(icao) DO UPDATE SET
                lat=excluded.lat, lon=excluded.lon, timezone=excluded.timezone,
                uses_fahrenheit=excluded.uses_fahrenheit
        """, (icao, city, lat, lon, timezone, int(uses_fahrenheit),
              datetime.utcnow().isoformat()))


def get_station(icao) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE icao=?", (icao,)).fetchone()
        return dict(row) if row else None


def get_all_stations() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM stations ORDER BY city").fetchall()]


def set_station_status(icao, status, history_days=None):
    with _conn() as conn:
        if history_days is not None:
            conn.execute("UPDATE stations SET status=?, history_days=? WHERE icao=?",
                         (status, history_days, icao))
        else:
            conn.execute("UPDATE stations SET status=? WHERE icao=?", (status, icao))


# ── Historical observations ───────────────────────────────────────────────────

def upsert_historical_obs(icao, obs_date: str, actual_high_c: float, source: str):
    """obs_date: 'YYYY-MM-DD'"""
    with _conn() as conn:
        conn.execute("""
            INSERT INTO historical_obs (icao, obs_date, actual_high_c, source, fetched_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(icao, obs_date, source) DO UPDATE SET
                actual_high_c=excluded.actual_high_c, fetched_at=excluded.fetched_at
        """, (icao, obs_date, actual_high_c, source, datetime.utcnow().isoformat()))


def get_historical_obs(icao, source=None) -> list[dict]:
    with _conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM historical_obs WHERE icao=? AND source=? ORDER BY obs_date",
                (icao, source)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM historical_obs WHERE icao=? ORDER BY obs_date", (icao,)
            ).fetchall()
        return [dict(r) for r in rows]


def count_historical_obs(icao) -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT obs_date) as c FROM historical_obs WHERE icao=?", (icao,)
        ).fetchone()
        return row["c"] if row else 0


# ── Model forecasts ───────────────────────────────────────────────────────────

def insert_forecast(icao, target_date: str, model_name: str, predicted_high_c: float):
    try:
        from datetime import date as _d
        lead_days = (_d.fromisoformat(target_date) - _d.today()).days
    except (ValueError, TypeError):
        lead_days = None
    with _conn() as conn:
        # Daily dedup: keep at most one row per (icao, target_date, model_name) per UTC day
        conn.execute("""
            DELETE FROM model_forecasts
            WHERE icao=? AND target_date=? AND model_name=? AND DATE(fetched_at)=DATE('now','utc')
        """, (icao, target_date, model_name))
        conn.execute("""
            INSERT INTO model_forecasts
                (icao, target_date, model_name, predicted_high_c, fetched_at, lead_time_days)
            VALUES (?,?,?,?,?,?)
        """, (icao, target_date, model_name, predicted_high_c,
              datetime.utcnow().isoformat(), lead_days))


def get_forecasts_for_date(icao, target_date: str) -> list[dict]:
    """Get the most recent forecast per model for a given target date."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT model_name, predicted_high_c, fetched_at
            FROM model_forecasts
            WHERE icao=? AND target_date=?
            ORDER BY model_name, fetched_at DESC
        """, (icao, target_date)).fetchall()
        # Keep only latest per model
        seen = {}
        for r in rows:
            if r["model_name"] not in seen:
                seen[r["model_name"]] = dict(r)
        return list(seen.values())


def get_historical_forecasts(icao, model_name=None) -> list[dict]:
    with _conn() as conn:
        if model_name:
            rows = conn.execute("""
                SELECT * FROM model_forecasts WHERE icao=? AND model_name=?
                ORDER BY target_date, fetched_at
            """, (icao, model_name)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM model_forecasts WHERE icao=?
                ORDER BY target_date, model_name, fetched_at
            """, (icao,)).fetchall()
        return [dict(r) for r in rows]


def get_recent_forecast_runs(icao: str, model_name: str, target_date: str, limit: int = 3) -> list[float]:
    """Get the last N predicted values for a model/date. Used for momentum alpha."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT predicted_high_c FROM model_forecasts
            WHERE icao=? AND model_name=? AND target_date=?
            ORDER BY fetched_at DESC
            LIMIT ?
        """, (icao, model_name, target_date, limit)).fetchall()
        return [r["predicted_high_c"] for r in rows]


def prune_old_forecasts(days_to_keep: int = 90) -> int:
    """Delete model forecast rows whose target_date is older than N days. Returns count deleted."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days_to_keep)).date().isoformat()
    with _conn() as conn:
        n = conn.execute(
            "DELETE FROM model_forecasts WHERE target_date < ?", (cutoff,)
        ).rowcount
    logger.info("Pruned %d model forecast rows with target_date older than %d days", n, days_to_keep)
    return n


# ── Bias corrections ──────────────────────────────────────────────────────────

def upsert_bias(icao, model_name, month: int, bias_c: float, sample_count: int):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO bias_corrections
                (icao, model_name, month, bias_c, sample_count, last_updated)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(icao, model_name, month) DO UPDATE SET
                bias_c=excluded.bias_c,
                sample_count=excluded.sample_count,
                last_updated=excluded.last_updated
        """, (icao, model_name, month, bias_c, sample_count,
              datetime.utcnow().isoformat()))


def get_bias(icao, model_name, month: int) -> float | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT bias_c FROM bias_corrections
            WHERE icao=? AND model_name=? AND month=?
        """, (icao, model_name, month)).fetchone()
        return row["bias_c"] if row else None


def get_all_biases(icao) -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bias_corrections WHERE icao=? ORDER BY model_name, month",
            (icao,)
        ).fetchall()]


def get_all_biases_batch() -> dict[str, list[dict]]:
    """Return all bias_corrections rows grouped by icao. One query instead of N."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bias_corrections ORDER BY icao, model_name, month"
        ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["icao"], []).append(d)
    return result


def get_recent_performance(icao: str, days: int = 7) -> list[dict]:
    """
    Get (actual - predicted) for the last N days for all models.
    Used for short-term persistence bias correction.
    """
    with _conn() as conn:
        rows = conn.execute("""
            SELECT h.obs_date, f.model_name, h.actual_high_c, f.predicted_high_c
            FROM historical_obs h
            JOIN model_forecasts f ON h.icao = f.icao AND h.obs_date = f.target_date
            WHERE h.icao = ?
              AND h.obs_date >= DATE('now', '-' || ? || ' days')
            ORDER BY h.obs_date DESC, f.fetched_at DESC
        """, (icao, days)).fetchall()

        # Deduplicate to get the latest forecast per day/model
        seen = set()
        result = []
        for r in rows:
            key = (r["obs_date"], r["model_name"])
            if key not in seen:
                seen.add(key)
                result.append(dict(r))
        return result


# ── Markets ───────────────────────────────────────────────────────────────────

def upsert_market(market_id, city, icao, target_date, question,
                  bucket_lo, bucket_hi, bucket_unit, clob_token_yes):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO markets
                (market_id, city, icao, target_date, question, bucket_lo, bucket_hi,
                 bucket_unit, clob_token_yes, fetched_at, active)
            VALUES (?,?,?,?,?,?,?,?,?,?,1)
            ON CONFLICT(market_id) DO UPDATE SET
                active=1, fetched_at=excluded.fetched_at,
                clob_token_yes=excluded.clob_token_yes
        """, (market_id, city, icao, target_date, question,
              bucket_lo, bucket_hi, bucket_unit, clob_token_yes,
              datetime.utcnow().isoformat()))


def get_active_markets(target_date=None, city=None) -> list[dict]:
    with _conn() as conn:
        clauses = ["active=1"]
        params = []
        if target_date:
            clauses.append("target_date=?")
            params.append(target_date)
        if city:
            clauses.append("city=?")
            params.append(city)
        where = "WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT * FROM markets {where} ORDER BY city, target_date, bucket_lo",
            params
        ).fetchall()
        return [dict(r) for r in rows]


def deactivate_markets_before(cutoff_date: str):
    with _conn() as conn:
        conn.execute("UPDATE markets SET active=0 WHERE target_date < ?", (cutoff_date,))


# ── Trades ────────────────────────────────────────────────────────────────────

def insert_trade(trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
                 bucket_unit, direction, entry_price, model_prob, market_prob, edge,
                 ensemble_std, size_usdc, kelly_f, target_date_end=None,
                 market_type="temperature", hub_weather_flag=None):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO trades
                (trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
                 bucket_unit, direction, entry_price, model_prob, market_prob, edge,
                 ensemble_std, size_usdc, kelly_f, status, entry_time, target_date_end,
                 market_type, hub_weather_flag)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?)
        """, (trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
              bucket_unit, direction, entry_price, model_prob, market_prob, edge,
              ensemble_std, size_usdc, kelly_f, datetime.utcnow().isoformat(),
              target_date_end, market_type,
              int(hub_weather_flag) if hub_weather_flag is not None else None))


def get_open_trades() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE status='open' ORDER BY entry_time DESC"
        ).fetchall()]


def get_all_trades(status=None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status=? ORDER BY entry_time DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_resolved_trades() -> list[dict]:
    """Return only won/lost trades — more efficient than get_all_trades() + filter."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status IN ('won','lost') ORDER BY entry_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_weather_fallback_trades() -> list[dict]:
    """Resolved trades where outcome was inferred from weather data, not Polymarket.
    These need re-verification once PM settles."""
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE outcome_source='weather_fallback'"
        ).fetchall()]


def update_trade_outcome(trade_id: str, new_outcome: str, outcome_source: str,
                         actual_high_c=None):
    """Correct the outcome of an already-resolved trade (e.g. PM overrides weather).

    Mirrors the bankroll_delta logic from resolve_trade (stake pre-deducted at entry):
      won/stop_loss → bankroll_delta = shares * exit_price
      lost          → bankroll_delta = 0
      void          → bankroll_delta = size
    """
    with _conn() as conn:
        trade = conn.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
        if not trade:
            return
        trade = dict(trade)
        old_outcome = trade["status"]
        size = trade["size_usdc"]
        entry_price = trade["entry_price"]
        old_exit = trade["exit_price"] or 0.0
        shares = size / entry_price

        # Compute what resolve_trade originally added to bankroll (must reverse this)
        if old_outcome in ("won", "stop_loss"):
            old_bankroll_delta = shares * old_exit
        elif old_outcome == "lost":
            old_bankroll_delta = 0.0
        else:  # void/voided/open
            old_bankroll_delta = size if old_outcome in ("void", "voided") else 0.0
        conn.execute("UPDATE bankroll SET balance = balance - ? WHERE id=1",
                     (old_bankroll_delta,))

        # Apply new outcome
        new_exit = 1.0 if new_outcome == "won" else 0.0
        if new_outcome == "won":
            new_bankroll_delta = shares * 1.0
            new_pnl = shares - size
        elif new_outcome == "lost":
            new_bankroll_delta = 0.0
            new_pnl = -size
        else:  # void
            new_bankroll_delta = size
            new_pnl = 0.0
        conn.execute("UPDATE bankroll SET balance = balance + ? WHERE id=1",
                     (new_bankroll_delta,))

        conn.execute("""
            UPDATE trades SET status=?, outcome_source=?, exit_price=?, pnl=?,
                              actual_high_c=COALESCE(?,actual_high_c)
            WHERE trade_id=?
        """, (new_outcome, outcome_source, new_exit, new_pnl, actual_high_c, trade_id))
        logger.info("Trade %s outcome corrected %s → %s (src=%s)",
                    trade_id[:8], old_outcome, new_outcome, outcome_source)


def update_trade_outcome_source(trade_id: str, outcome_source: str):
    """Update just the outcome_source field without changing the outcome."""
    with _conn() as conn:
        conn.execute("UPDATE trades SET outcome_source=? WHERE trade_id=?",
                     (outcome_source, trade_id))


def resolve_trade(trade_id, actual_high_c, outcome: str, exit_price: float,
                  outcome_source: str = "polymarket"):
    """outcome: 'won' | 'lost' | 'void' | 'voided' | 'stop_loss'

    Bankroll accounting (stake is PRE-DEDUCTED at entry via adjust_bankroll):
      won        → return stake + profit  (bankroll += shares * exit_price)
      lost       → nothing returned       (bankroll += 0; stake already gone at entry)
      stop_loss  → return current value   (bankroll += shares * exit_price, may be < cost)
      void       → return stake           (bankroll += size)

    pnl column stores total return relative to cost (e.g. -size for lost) for display.
    Do NOT use pnl to update bankroll — stake was already deducted at entry.
    """
    with _conn() as conn:
        trade = conn.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
        if not trade:
            raise ValueError(f"Trade {trade_id} not found")
        trade = dict(trade)
        size = trade["size_usdc"]
        shares = size / trade["entry_price"]

        # pnl: display-only (total return − cost)
        if outcome in ("won", "stop_loss"):
            pnl = shares * exit_price - size
        elif outcome == "lost":
            pnl = -size   # display: you lost your stake
        else:  # void / voided
            pnl = 0.0

        # bankroll_delta: what we physically receive back (stake was already removed at entry)
        if outcome in ("won", "stop_loss"):
            bankroll_delta = shares * exit_price   # stake + profit (or partial return for stop-loss)
        elif outcome == "lost":
            bankroll_delta = 0.0                   # nothing returned; stake is gone
        else:  # void / voided
            bankroll_delta = size                  # return full stake

        conn.execute("""
            UPDATE trades SET status=?, actual_high_c=?, exit_price=?,
                              pnl=?, resolved_at=?, outcome_source=?
            WHERE trade_id=?
        """, (outcome, actual_high_c, exit_price, pnl,
              datetime.utcnow().isoformat(), outcome_source, trade_id))
        conn.execute("UPDATE bankroll SET balance = balance + ? WHERE id=1", (bankroll_delta,))
        return pnl


def open_trade_atomic(trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
                      bucket_unit, direction, entry_price, model_prob, market_prob, edge,
                      ensemble_std, size_usdc, kelly_f, target_date_end=None,
                      market_type="temperature", hub_weather_flag=None,
                      clob_token_yes=""):
    """
    Deduct stake from bankroll AND insert trade record in a single transaction.
    If either operation fails the entire transaction rolls back, preventing the
    'stake deducted but no trade record' crash scenario.
    """
    with _conn() as conn:
        conn.execute("UPDATE bankroll SET balance = balance - ? WHERE id=1", (size_usdc,))
        conn.execute("""
            INSERT INTO trades
                (trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
                 bucket_unit, direction, entry_price, model_prob, market_prob, edge,
                 ensemble_std, size_usdc, kelly_f, status, entry_time, target_date_end,
                 market_type, hub_weather_flag, clob_token_yes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?,?)
        """, (trade_id, market_id, city, icao, target_date, bucket_lo, bucket_hi,
              bucket_unit, direction, entry_price, model_prob, market_prob, edge,
              ensemble_std, size_usdc, kelly_f, datetime.utcnow().isoformat(),
              target_date_end, market_type,
              int(hub_weather_flag) if hub_weather_flag is not None else None,
              clob_token_yes or ""))


def already_in_market(market_id) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT trade_id FROM trades WHERE market_id=? AND status='open'",
            (market_id,)
        ).fetchone()
        return row is not None


# ── Daily PnL ─────────────────────────────────────────────────────────────────

def upsert_daily_pnl(pnl_date: str, starting: float, ending: float,
                     placed: int, resolved: int, wins: int, losses: int):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO daily_pnl
                (pnl_date, starting_bankroll, ending_bankroll,
                 trades_placed, trades_resolved, win_count, loss_count)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(pnl_date) DO UPDATE SET
                ending_bankroll=excluded.ending_bankroll,
                trades_placed=trades_placed + excluded.trades_placed,
                trades_resolved=trades_resolved + excluded.trades_resolved,
                win_count=win_count + excluded.win_count,
                loss_count=loss_count + excluded.loss_count
        """, (pnl_date, starting, ending, placed, resolved, wins, losses))


def get_daily_pnl() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM daily_pnl ORDER BY pnl_date"
        ).fetchall()]


# ── Scan log ──────────────────────────────────────────────────────────────────

def log_event(event_type: str, message: str, city=None, icao=None, data=None):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO scan_log (timestamp, event_type, city, icao, message, data_json)
            VALUES (?,?,?,?,?,?)
        """, (datetime.utcnow().isoformat(), event_type, city, icao,
              message, json.dumps(data) if data else None))


# ── Climatology ───────────────────────────────────────────────────────────────

def upsert_climatology(icao: str, month: int, mean_c: float, std_c: float,
                       p10_c: float, p90_c: float, sample_years: int):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO climatology
                (icao, month, mean_c, std_c, p10_c, p90_c, sample_years, last_updated)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(icao, month) DO UPDATE SET
                mean_c=excluded.mean_c, std_c=excluded.std_c,
                p10_c=excluded.p10_c, p90_c=excluded.p90_c,
                sample_years=excluded.sample_years,
                last_updated=excluded.last_updated
        """, (icao, month, mean_c, std_c, p10_c, p90_c, sample_years,
              datetime.utcnow().isoformat()))


def get_climatology(icao: str, month: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM climatology WHERE icao=? AND month=?", (icao, month)
        ).fetchone()
        return dict(row) if row else None


def get_all_climatology(icao: str) -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM climatology WHERE icao=? ORDER BY month", (icao,)
        ).fetchall()]


# ── Price history ─────────────────────────────────────────────────────────────

def record_price(market_id: str, mid_price: float,
                 model_prob: float | None = None, edge: float | None = None):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO price_history (market_id, scanned_at, mid_price, model_prob, edge)
            VALUES (?,?,?,?,?)
        """, (market_id, datetime.utcnow().isoformat(), mid_price, model_prob, edge))


def get_recent_prices(market_id: str, limit: int = 3) -> list[dict]:
    """Most recent price snapshots, newest first."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM price_history WHERE market_id=?
            ORDER BY scanned_at DESC LIMIT ?
        """, (market_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_price_at_time(market_id: str, target_ts: str, window_hours: int = 6) -> float | None:
    """Return the mid_price closest to target_ts within ±window_hours, or None."""
    with _conn() as conn:
        row = conn.execute("""
            SELECT mid_price,
                   ABS(strftime('%s', scanned_at) - strftime('%s', ?)) AS diff_secs
            FROM price_history
            WHERE market_id = ?
            ORDER BY diff_secs ASC
            LIMIT 1
        """, (target_ts, market_id)).fetchone()
        if row is None:
            return None
        if row["diff_secs"] > window_hours * 3600:
            return None
        return float(row["mid_price"])


def bulk_insert_prices(rows: list[dict]):
    """Batch insert price history rows. Silently skips duplicates."""
    if not rows:
        return
    with _conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO price_history
                (market_id, token_id, scanned_at, mid_price)
            VALUES (:market_id, :token_id, :scanned_at, :mid_price)
        """, rows)


# ── Calibration predictions ───────────────────────────────────────────────────

def record_prediction(pred_id: str, market_id: str,
                      model_prob: float, market_prob: float):
    with _conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO calibration_predictions
                (pred_id, market_id, scanned_at, model_prob, market_prob)
            VALUES (?,?,?,?,?)
        """, (pred_id, market_id, datetime.utcnow().isoformat(), model_prob, market_prob))


def resolve_prediction(market_id: str, outcome: float):
    """outcome: 1.0 = YES resolved, 0.0 = NO resolved."""
    with _conn() as conn:
        conn.execute("""
            UPDATE calibration_predictions
            SET outcome=?, resolved_at=?
            WHERE market_id=? AND outcome IS NULL
        """, (outcome, datetime.utcnow().isoformat(), market_id))


# ── TSA calibration ───────────────────────────────────────────────────────────

def record_tsa_prediction(pred_id: str, market_id: str,
                          model_prob: float, market_prob: float,
                          tsa_mean_m: float | None = None,
                          tsa_std_m: float | None = None,
                          hub_weather_flag: bool | None = None):
    """Log a TSA signal snapshot for calibration tracking."""
    with _conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO tsa_calibration
                (pred_id, market_id, scanned_at, model_prob, market_prob,
                 tsa_mean_m, tsa_std_m, hub_weather_flag)
            VALUES (?,?,?,?,?,?,?,?)
        """, (pred_id, market_id, datetime.utcnow().isoformat(),
              model_prob, market_prob, tsa_mean_m, tsa_std_m,
              int(hub_weather_flag) if hub_weather_flag is not None else None))


def resolve_tsa_prediction(market_id: str, outcome: float):
    """outcome: 1.0 = YES resolved, 0.0 = NO resolved."""
    with _conn() as conn:
        conn.execute("""
            UPDATE tsa_calibration
            SET outcome=?, resolved_at=?
            WHERE market_id=? AND outcome IS NULL
        """, (outcome, datetime.utcnow().isoformat(), market_id))


def get_kv(key: str) -> str | None:
    """Retrieve a key-value pair (used for storing crypto reference prices)."""
    with _conn() as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_kv(key: str, value: str):
    """Store a key-value pair."""
    with _conn() as conn:
        conn.execute("""
            INSERT INTO kv_store (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (key, value, datetime.utcnow().isoformat()))


def get_calibration_predictions(resolved_only: bool = False) -> list[dict]:
    with _conn() as conn:
        if resolved_only:
            rows = conn.execute(
                "SELECT * FROM calibration_predictions WHERE outcome IS NOT NULL "
                "ORDER BY scanned_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calibration_predictions ORDER BY scanned_at"
            ).fetchall()
        return [dict(r) for r in rows]
