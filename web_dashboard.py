#!/usr/bin/env python3
"""Web dashboard — run: python web_dashboard.py"""
import logging
import os
import subprocess
import sys
import time
import threading
import traceback
import uuid
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request, render_template
import requests as _req
import db
from metrics.pnl import compute_pnl_summary
from metrics.calibration import compute_calibration
from metrics.sharpe import compute_sharpe

logger = logging.getLogger(__name__)
app = Flask(__name__)

# ── Response cache ─────────────────────────────────────────────────────────────
_api_cache: dict = {}
_api_lock = threading.Lock()
CACHE_TTL = 20

_slug_cache: dict[str, dict] = {}
_jobs: dict[str, dict] = {}
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Empty calibration payload for live Polymarket-only view (bot metrics stay in paper)
_CAL_PLACEHOLDER = {
    "accuracy": 0.0,
    "mean_model_error": 0.0,
    "mean_market_error": 0.0,
    "model_closer_count": 0,
    "n": 0,
}


def _run_job(job_id: str, cmd_flag: str, mode: str = "paper"):
    try:
        result = subprocess.run(
            [sys.executable, "main.py", "--mode", mode, cmd_flag],
            capture_output=True, text=True, timeout=600,
            cwd=_BOT_DIR,
        )
        output = (result.stdout + result.stderr).strip()
        _jobs[job_id] = {
            "status": "done" if result.returncode == 0 else "error",
            "output": output[-4000:],
        }
        _api_cache.pop(mode, None)
    except subprocess.TimeoutExpired:
        _jobs[job_id] = {"status": "error", "output": "Timed out after 10 minutes."}
    except Exception as e:
        _jobs[job_id] = {"status": "error", "output": str(e)}


@app.route("/api/run/<cmd>", methods=["POST"])
def run_cmd(cmd):
    allowed = {"scan": "--scan", "resolve": "--resolve", "monitor": "--monitor"}
    if cmd not in allowed:
        return jsonify({"error": "unknown command"}), 400
    mode = request.args.get("mode", "paper")
    running = [j for j in _jobs.values() if j.get("status") == "running" and j.get("cmd") == cmd]
    if running:
        return jsonify({"error": f"{cmd} already running"}), 409
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "running", "output": "", "cmd": cmd}
    t = threading.Thread(target=_run_job, args=(job_id, allowed[cmd], mode), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/run/status/<job_id>")
def job_status(job_id):
    return jsonify(_jobs.get(job_id, {"status": "unknown", "output": ""}))


def _get_market_meta(clob_token: str) -> dict:
    if clob_token in _slug_cache:
        return _slug_cache[clob_token]
    try:
        r = _req.get("https://gamma-api.polymarket.com/markets",
                     params={"clob_token_ids": clob_token}, timeout=6)
        data = r.json()
        if data:
            m = data[0]
            slug = m.get("slug", "")
            events = m.get("events", [])
            event_slug = events[0].get("slug", "") if events else ""
            result = {"slug": slug, "event_slug": event_slug}
            _slug_cache[clob_token] = result
            return result
    except Exception:
        pass
    return {"slug": "", "event_slug": ""}


def _enrich_trades(trades, db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    enriched = []
    try:
        for t in trades:
            row = dict(t)
            if row.get("pm_row"):
                enriched.append(row)
                continue
            m = None
            if t.get("market_id"):
                cur = conn.execute(
                    "SELECT market_id, question, clob_token_yes FROM markets "
                    "WHERE market_id=? LIMIT 1",
                    (t["market_id"],)
                )
                m = cur.fetchone()
            if not m:
                cur = conn.execute(
                    "SELECT market_id, question, clob_token_yes FROM markets "
                    "WHERE city=? AND target_date=? AND bucket_lo IS ? AND bucket_hi IS ? AND bucket_unit=? LIMIT 1",
                    (t["city"], str(t["target_date"]), t["bucket_lo"], t["bucket_hi"], t["bucket_unit"])
                )
                m = cur.fetchone()
            if m:
                row["market_id"] = m["market_id"]
                row["question"] = m["question"]
                row["clob_token_yes"] = m["clob_token_yes"]
            else:
                row.setdefault("market_id", t.get("market_id", ""))
                row.setdefault("question", "")
                row.setdefault("clob_token_yes", "")
            enriched.append(row)
    finally:
        conn.close()
    return enriched


def _build_polymarket_live_dashboard(db_path: str) -> dict:
    """
    Entire live view from Polymarket public Data API + CLOB cash (same as UI).
    """
    from broker.live_broker import (
        get_clob_balance,
        get_clob_positions,
        get_polymarket_closed_positions,
        get_polymarket_positions_value_usd,
        get_proxy_address,
    )

    proxy = get_proxy_address()
    if not proxy:
        raise RuntimeError("POLYMARKET_PROXY_ADDRESS not set in environment (.env)")

    cash = float(get_clob_balance() or 0.0)
    raw_open = get_clob_positions()
    raw_closed = get_polymarket_closed_positions(limit=500)

    pos_value_api = get_polymarket_positions_value_usd()
    positions_sum = sum(float(p.get("currentValue") or 0) for p in raw_open)
    positions_value = pos_value_api if pos_value_api is not None else positions_sum

    unrealized = sum(float(p.get("cashPnl") or 0) for p in raw_open)
    realized = sum(float(p.get("realizedPnl") or 0) for p in raw_closed)
    total_pnl = unrealized + realized

    portfolio_value = cash + positions_value
    cost_basis = max(0.01, portfolio_value - total_pnl)
    pct_return = (total_pnl / cost_basis) * 100.0

    realized_list = [float(p.get("realizedPnl") or 0) for p in raw_closed]
    wins_list = [x for x in realized_list if x > 0]
    losses_list = [x for x in realized_list if x < 0]
    n_resolved = len(raw_closed)
    n_wins = len(wins_list)
    n_losses = len(losses_list)

    rows_open = []
    for i, p in enumerate(raw_open):
        tid = f"pm-open-{p.get('conditionId', '')[:20]}-{i}"
        rows_open.append({
            "trade_id": tid,
            "market_id": p.get("conditionId", ""),
            "city": (p.get("title") or "Market")[:100],
            "target_date": str(p.get("endDate") or "")[:16],
            "bucket_lo": None,
            "bucket_hi": None,
            "bucket_unit": "PM",
            "direction": p.get("outcome", "—"),
            "entry_price": float(p.get("avgPrice") or 0),
            "size_usdc": float(p.get("currentValue") or 0),
            "model_prob": float(p.get("curPrice") or 0),
            "market_prob": float(p.get("curPrice") or 0),
            "edge": float(p.get("cashPnl") or 0),
            "question": p.get("title", ""),
            "clob_token_yes": str(p.get("asset") or ""),
            "pm_row": True,
            "pm_initial": float(p.get("initialValue") or 0),
        })

    closed_sorted = sorted(
        raw_closed,
        key=lambda x: int(x.get("timestamp") or 0),
        reverse=True,
    )
    rows_closed = []
    for i, p in enumerate(closed_sorted):
        rp = float(p.get("realizedPnl") or 0)
        tid = f"pm-closed-{p.get('conditionId', '')[:20]}-{i}"
        rows_closed.append({
            "trade_id": tid,
            "city": (p.get("title") or "Market")[:100],
            "target_date": str(p.get("endDate") or "")[:16],
            "bucket_lo": None,
            "bucket_hi": None,
            "bucket_unit": "PM",
            "direction": p.get("outcome", "—"),
            "entry_price": float(p.get("avgPrice") or 0),
            "size_usdc": float(p.get("totalBought") or 0),
            "model_prob": 0.0,
            "market_prob": 0.0,
            "edge": 0.0,
            "pnl": rp,
            "status": "won" if rp >= 0 else "lost",
            "actual_high_c": None,
            "question": p.get("title", ""),
            "clob_token_yes": str(p.get("asset") or ""),
            "pm_row": True,
        })

    pnl = {
        "bankroll": cash,
        "cash": cash,
        "deployed": positions_value,
        "positions_value": positions_value,
        "portfolio_value": portfolio_value,
        "available": cash,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "total_pnl": total_pnl,
        "pct_return": pct_return,
        "n_resolved": n_resolved,
        "n_open": len(raw_open),
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": (n_wins / n_resolved * 100.0) if n_resolved else 0.0,
        "avg_win": sum(wins_list) / len(wins_list) if wins_list else 0.0,
        "avg_loss": sum(losses_list) / len(losses_list) if losses_list else 0.0,
    }

    db.set_mode("live")
    all_biases = db.get_all_biases_batch()
    stations_raw = db.get_all_stations()
    stations = []
    for s in sorted(stations_raw, key=lambda x: x["city"]):
        biases = all_biases.get(s["icao"], [])
        n_b = len(biases)
        avg_b = sum(abs(b["bias_c"]) for b in biases) / n_b if biases else None
        stations.append({
            "city": s["city"],
            "icao": s["icao"],
            "status": s["status"],
            "history_days": s["history_days"],
            "avg_bias": avg_b,
        })

    from ops_state import get_ops_snapshot
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "live",
        "db_file": os.path.basename(db_path),
        "live_pm_ui": True,
        "data_source": "polymarket",
        "open_count": len(rows_open),
        "history_count": len(rows_closed),
        "pnl": pnl,
        "cal": _CAL_PLACEHOLDER,
        "sharpe": None,
        "positions": rows_open,
        "history": rows_closed,
        "stations": stations,
        "ops": get_ops_snapshot(),
    }


def _build_data(mode: str) -> dict:
    db.set_mode(mode)
    current_path = db.DB_PATH

    if mode == "live":
        return _build_polymarket_live_dashboard(current_path)

    pnl = compute_pnl_summary()
    cal = compute_calibration()
    sharpe = compute_sharpe()
    open_trades_raw = db.get_open_trades()
    all_trades = db.get_all_trades()
    history_raw = [t for t in all_trades if t["status"] in ("won", "lost", "stop_loss")]
    trades = _enrich_trades(open_trades_raw, current_path)
    history = _enrich_trades(history_raw, current_path)

    all_biases = db.get_all_biases_batch()
    stations_raw = db.get_all_stations()
    stations = []
    for s in sorted(stations_raw, key=lambda x: x["city"]):
        biases = all_biases.get(s["icao"], [])
        n_b = len(biases)
        avg_b = sum(abs(b["bias_c"]) for b in biases) / n_b if biases else None
        stations.append({
            "city": s["city"],
            "icao": s["icao"],
            "status": s["status"],
            "history_days": s["history_days"],
            "avg_bias": avg_b,
        })

    from ops_state import get_ops_snapshot
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "db_file": os.path.basename(current_path),
        "live_pm_ui": False,
        "open_count": len(open_trades_raw),
        "history_count": len(history_raw),
        "pnl": pnl,
        "cal": cal,
        "sharpe": sharpe,
        "positions": trades,
        "history": history,
        "stations": stations,
        "ops": get_ops_snapshot(),
    }


@app.route("/api/data")
def api_data():
    mode = request.args.get("mode", "paper")
    now = time.time()
    force = request.args.get("force", "") == "1"

    if not force:
        cached = _api_cache.get(mode)
        if cached and (now - cached["ts"]) < CACHE_TTL:
            return jsonify(cached["data"])

    with _api_lock:
        if not force:
            cached = _api_cache.get(mode)
            if cached and (now - cached["ts"]) < CACHE_TTL:
                return jsonify(cached["data"])

        try:
            data = _build_data(mode)
            _api_cache[mode] = {"ts": now, "data": data}
            return jsonify(data)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("api_data(%s) error: %s\n%s", mode, e, tb)
            stale = _api_cache.get(mode)
            if stale:
                d = dict(stale["data"])
                d["stale"] = True
                d["stale_error"] = str(e)
                return jsonify(d)
            return jsonify({"error": str(e), "traceback": tb}), 500


@app.route("/api/price-history")
def price_history():
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "no token"}), 400
    try:
        r = _req.get("https://clob.polymarket.com/prices-history",
                     params={"market": token, "interval": "max", "fidelity": 60}, timeout=8)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/market-meta")
def market_meta():
    token = request.args.get("token", "")
    if not token:
        return jsonify({}), 400
    return jsonify(_get_market_meta(token))


@app.route("/api/clob-balance")
def clob_balance():
    try:
        from broker.live_broker import get_clob_balance
        bal = get_clob_balance()
        return jsonify({"balance": bal})
    except Exception as e:
        return jsonify({"balance": None, "error": str(e)})


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    db.init_db()
    print("\n  Dashboard → http://localhost:5050\n")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
