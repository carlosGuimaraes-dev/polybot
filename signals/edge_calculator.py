"""
Edge calculator — the core signal.

For each bucket in a temperature market:
  1. Fit a Student's t distribution to the 5 bias-corrected model forecasts
  2. Compute P(temp falls in bucket) using scipy.stats.t (df=FORECAST_T_DF)
  3. Get CLOB mid-price (market implied probability)
  4. edge = model_prob - market_implied_prob
  5. Only trade if abs(edge) > MIN_EDGE and ensemble is in sweet spot

Unit handling: all internal calculations in °C. Bucket boundaries converted
from °F to °C if the market uses Fahrenheit.
"""
import logging
import math
import time as _time
from scipy.stats import t as _t
from config import MIN_EDGE, CITIES, HIGH_CONVICTION_EDGE, HIGH_CONVICTION_KELLY_MULT, FORECAST_T_DF, NO_ENTRY_MIN_PRICE, NO_ENTRY_MAX_PRICE, NO_MIN_ENSEMBLE_STD
from signals.ensemble import compute_ensemble_stats
from signals.nowcaster import nowcast_confidence, get_running_max_c, compute_nowcast_bucket_prob

logger = logging.getLogger(__name__)

# ── Calibration cache ─────────────────────────────────────────────────────────
# compute_calibration() does a full resolved-trades DB read. Calling it once per
# bucket (20 cities × 8 buckets × 3 scans/day = 480 reads/day) is wasteful as
# trade history grows. Cache for 5 minutes — more than enough for a scan run.
_cal_cache: dict = {"by_city": {}}
_cal_cache_time: float = 0.0
_CAL_CACHE_TTL = 300.0  # seconds


def _get_city_bss(city_name: str) -> float | None:
    """
    Return the per-city Brier Skill Score from a 5-min cached calibration read.
    Returns None if the city has fewer than 20 resolved trades (too noisy to trust).
    Never raises — calibration must not block trades.
    """
    global _cal_cache, _cal_cache_time
    now = _time.monotonic()
    if now - _cal_cache_time > _CAL_CACHE_TTL:
        try:
            from metrics.calibration import compute_calibration
            _cal_cache = compute_calibration()
            _cal_cache_time = now
        except Exception:
            pass  # keep stale cache rather than blocking
    city_stats = _cal_cache.get("by_city", {}).get(city_name, {})
    if city_stats.get("n", 0) >= 20:
        return city_stats.get("brier_skill")
    return None


from utils import f_to_c as _f_to_c


def bucket_bounds_to_celsius(lo, hi, unit: str) -> tuple[float, float]:
    """Convert bucket bounds to °C. None = unbounded."""
    if unit == "F":
        lo_c = _f_to_c(lo) if lo is not None else None
        hi_c = _f_to_c(hi) if hi is not None else None
    else:
        lo_c = lo
        hi_c = hi
    return lo_c, hi_c


def model_prob_for_bucket(ensemble_mean_c: float, effective_std: float,
                           lo_c: float | None, hi_c: float | None) -> float:
    """P(temp in [lo_c, hi_c]) under t(df=FORECAST_T_DF, mean, eff_std).

    Student's t with low df gives heavier tails than Gaussian, preventing the
    bot from under-pricing extreme outlier buckets (record heatwaves, cold snaps).
    """
    lo_val = lo_c if lo_c is not None else -math.inf
    hi_val = hi_c if hi_c is not None else math.inf
    p = _t.cdf(hi_val, FORECAST_T_DF, loc=ensemble_mean_c, scale=effective_std) - \
        _t.cdf(lo_val, FORECAST_T_DF, loc=ensemble_mean_c, scale=effective_std)
    # Floor at 0.5% — never assign literal 0 probability to a finite bucket.
    # A model_prob=0.000 on a bucket that resolves YES gives Brier=1.0 (worst possible).
    # The market always prices finite tail risk; we should too.
    return float(max(0.005, min(0.995, p)))



def weekly_market_prob(
    ensemble_mean_c: float,
    effective_std: float,
    bucket_lo_c: float | None,
    bucket_hi_c: float | None,
    n_days: int,
    per_day_means: list[float] | None = None,
) -> float:
    """
    P(daily max reaches bucket at least once over n_days).

    For a lower-bound bucket (lo, +∞): P(at least one day >= lo)
      = 1 - P(all days < lo) = 1 - P(day < lo)^n  (assuming independence)
    For an upper-bound / range bucket, use complement:
      P(max ever in [lo, hi]) ≈ approximated via envelope.

    Day-to-day weather is autocorrelated (ρ ≈ 0.5 for adjacent days in a week).
    We account for this with an effective sample size:
      n_eff = n / (1 + (n-1) * RHO)
    After collecting per-day probabilities, the product is replaced with
    geometric-mean ^ n_eff which shrinks the "multi-day boost" for correlated days.

    per_day_means: if provided, use the actual per-day forecast mean instead of
    ensemble_mean_c for each day (more accurate for weekly markets).
    """
    DAY_CORRELATION = 0.5   # ρ between adjacent daily forecasts in a week
    n_eff = n_days / (1.0 + (n_days - 1) * DAY_CORRELATION)

    # Std grows with forecast lead: add 0.2°C per day beyond day 1
    log_p_below_sum   = 0.0   # sum of log P(day < lo) for geometric-mean approach
    log_p_above_sum   = 0.0
    log_p_outside_sum = 0.0

    lo = bucket_lo_c if bucket_lo_c is not None else -math.inf
    hi = bucket_hi_c if bucket_hi_c is not None else math.inf

    for day in range(n_days):
        day_mean = per_day_means[day] if per_day_means and day < len(per_day_means) else ensemble_mean_c
        day_std    = math.sqrt(effective_std ** 2 + (0.2 * day) ** 2)
        p_below    = _t.cdf(lo, FORECAST_T_DF, loc=day_mean, scale=day_std)
        p_above    = 1.0 - _t.cdf(hi, FORECAST_T_DF, loc=day_mean, scale=day_std)
        p_out      = p_below + p_above
        # Clamp to avoid log(0)
        log_p_below_sum   += math.log(max(p_below, 1e-12))
        log_p_above_sum   += math.log(max(p_above, 1e-12))
        log_p_outside_sum += math.log(max(p_out, 1e-12))

    # Geometric mean raised to n_eff (instead of product of n independent values)
    p_all_below   = math.exp(log_p_below_sum   / n_days * n_eff)
    p_all_above   = math.exp(log_p_above_sum   / n_days * n_eff)
    p_all_outside = math.exp(log_p_outside_sum / n_days * n_eff)

    if bucket_lo_c is not None and bucket_hi_c is None:
        # Pure lower bound: P(at least one day >= lo)
        return float(max(0.0, min(1.0, 1.0 - p_all_below)))
    elif bucket_hi_c is not None and bucket_lo_c is None:
        # Pure upper bound: P(at least one day < hi)
        return float(max(0.0, min(1.0, 1.0 - p_all_above)))
    else:
        # Range bucket: P(at least one day in [lo, hi])
        # = 1 - P(all days outside [lo, hi])
        return float(max(0.0, min(1.0, 1.0 - p_all_outside)))


def _climo_blend(base_prob, ensemble_mean_c, effective_std,
                 lo_c, hi_c, climo):
    """
    Blend in climatological prior when available.

    If ensemble deviates from climo mean by more than 1 climo std, blend a small
    weight of the climo probability into the model probability. This represents
    the market's anchoring tendency toward historical norms.

    Returns (blended_prob, climo_mean_c, climo_deviation_c, climo_std_c).
    """
    if climo is None:
        return base_prob, None, None, None  # added None for climo_std_c

    climo_mean = climo["mean_c"]
    climo_std  = climo["std_c"]
    deviation  = ensemble_mean_c - climo_mean

    climo_prob = model_prob_for_bucket(climo_mean, climo_std, lo_c, hi_c)

    deviation_sigmas = abs(deviation) / max(climo_std, 0.5)
    climo_weight = max(0.0, 0.15 - 0.05 * deviation_sigmas)

    blended = (1.0 - climo_weight) * base_prob + climo_weight * climo_prob
    logger.debug(
        "Climo blend: base=%.3f climo=%.3f weight=%.2f blended=%.3f "
        "(climo_mean=%.1f dev=%.1f)",
        base_prob, climo_prob, climo_weight, blended, climo_mean, deviation
    )
    return blended, round(climo_mean, 2), round(deviation, 2), round(climo_std, 2)


def compute_edge(
    market: dict,
    corrected_forecasts: dict[str, float],
    market_implied_prob: float,
    city_name: str,
    apply_nowcast: bool = True,
    icao: str | None = None,
    model_weights: dict[str, float] | None = None,
    bid: float | None = None,
    ask: float | None = None,
    per_day_corrected: list[dict[str, float]] | None = None,
    precip_prob: float = 0.0,
) -> dict | None:
    """
    Compute the full edge signal for one market bucket.

    market: DB market row or parsed market dict with keys:
        bucket_lo, bucket_hi, bucket_unit, target_date, city
    corrected_forecasts: {model_name: corrected_high_c}
    market_implied_prob: CLOB mid-price for YES outcome
    city_name: for nowcast lookup
    icao: for climatology lookup (optional, derived from CITIES if absent)
    bid: best CLOB bid for YES token (used for accurate NO entry price)
    ask: best CLOB ask for YES token (used for accurate YES entry price)
    per_day_corrected: for weekly markets, list of {model_name: corrected_high_c}
        per calendar day — enables per-day mean variation in weekly_market_prob

    Returns a signal dict, or None if the market should be skipped.
    """
    from config import (MIN_EDGE, MAX_TRADE_FRACTION, KELLY_FRACTION as KF, CITIES,
                    MIN_EDGE_RECENT_MULTIPLIER, MIN_EDGE_RECENT_DAYS)
    import db

    target_date = str(market.get("target_date", ""))
    bucket_lo   = market.get("bucket_lo")
    bucket_hi   = market.get("bucket_hi")
    bucket_unit = market.get("bucket_unit", "C")

    # Resolve icao for DB lookups
    if icao is None and city_name in CITIES:
        icao = CITIES[city_name]["icao"]

    # 1. Ensemble statistics
    try:
        ensemble = compute_ensemble_stats(corrected_forecasts, 
                                         override_weights=model_weights,
                                         target_date=target_date)
    except ValueError as e:
        logger.warning("Ensemble stats failed: %s", e)
        return None

    if not ensemble["tradeable"]:
        logger.debug("Skipping: ensemble %s (std=%.2f°C)", ensemble["score"], ensemble["std_c"])
        return None

    # 2. Convert bucket bounds to °C
    lo_c, hi_c = bucket_bounds_to_celsius(bucket_lo, bucket_hi, bucket_unit)

    # 2b. Lead-time scaling: forecast uncertainty grows with horizon.
    # Reference point = 3 days. ECMWF empirical: ~sqrt relationship.
    # Clamped to [0.7×, 1.5×] to prevent extreme size distortions.
    from datetime import date as _date_cls
    try:
        lead_days = max(1, (_date_cls.fromisoformat(target_date) - _date_cls.today()).days)
        horizon_scale = max(0.7, min(1.5, math.sqrt(lead_days / 3.0)))
    except (ValueError, TypeError):
        horizon_scale = 1.0
    effective_std_scaled = ensemble["effective_std"] * horizon_scale

    # 3. Precipitation Chill Alpha (Rain-cooling penalty)
    # If rain prob > 40%, the daily high is likely capped by cloud cover and evaporative cooling.
    # Apply a -0.4°C to -1.2°C penalty to the ensemble mean.
    ensemble_mean = ensemble["mean_c"]
    rain_penalty = 0.0
    if precip_prob > 40:
        # Penalty scales from 0.4°C at 40% prob to 1.2°C at 100% prob
        rain_penalty = 0.4 + (precip_prob - 40) * (0.8 / 60)
        ensemble_mean -= rain_penalty
        logger.info("Applying Precipitation Chill penalty: -%.2f°C (prob=%.0f%%)", 
                    rain_penalty, precip_prob)

    # 4. Base model probability (daily or weekly)
    market_type = market.get("market_type", "daily")
    if market_type == "weekly":
        try:
            d_start = _date_cls.fromisoformat(str(market.get("target_date", target_date)))
            d_end   = _date_cls.fromisoformat(str(market.get("target_date_end", target_date)))
            n_days  = max(1, (d_end - d_start).days + 1)
        except (ValueError, TypeError):
            n_days = 7

        # Compute per-day ensemble means from per_day_corrected if available
        per_day_means = None
        if per_day_corrected:
            from signals.ensemble import compute_ensemble_stats as _ces
            per_day_means = []
            for day_fc in per_day_corrected:
                try:
                    day_ens = _ces(day_fc, override_weights=model_weights)
                    per_day_means.append(day_ens["mean_c"])
                except ValueError:
                    per_day_means.append(ensemble_mean)

        base_prob = weekly_market_prob(
            ensemble_mean, effective_std_scaled, lo_c, hi_c, n_days,
            per_day_means=per_day_means,
        )
    else:
        base_prob = model_prob_for_bucket(ensemble_mean, effective_std_scaled, lo_c, hi_c)

    # 5. Anchor divergence: compare ensemble to "best_match" as market-anchor proxy
    #    best_match is the most publicly visible single-model forecast on Open-Meteo
    anchor_model = corrected_forecasts.get("meteofrance") or corrected_forecasts.get("gfs")
    anchor_divergence_c = None
    if anchor_model is not None:
        anchor_divergence_c = round(ensemble_mean - anchor_model, 2)

    # 6. Climatological prior blend
    climo = None
    climo_mean_c = None
    climo_deviation_c = None
    if icao and target_date:
        month = int(target_date[5:7])
        climo = db.get_climatology(icao, month)

    blended_prob, climo_mean_c, climo_deviation_c, climo_std_c = _climo_blend(
        base_prob, ensemble_mean, effective_std_scaled,
        lo_c, hi_c, climo
    )

    # 6. Nowcast blend (if after 2pm local)
    final_model_prob = blended_prob
    nowcast_weight = 0.0
    running_max = None
    sources = None

    if apply_nowcast and city_name in CITIES:
        cfg = CITIES[city_name]
        nowcast_weight = nowcast_confidence(cfg["timezone"])
        if nowcast_weight > 0.05:
            # Use cached values if caller pre-fetched them (_nowcast_fetched avoids re-calling)
            if market.get("_nowcast_fetched"):
                running_max = market.get("_cached_running_max_c")
                temp_rate   = market.get("_cached_temp_rate_c_per_h")
                sources     = market.get("_cached_running_max_sources")
            else:
                running_max, temp_rate, sources = get_running_max_c(city_name)
            if running_max is None:
                logger.debug("%s: nowcast unavailable, using model only", city_name)
            else:
                final_model_prob = compute_nowcast_bucket_prob(
                    running_max, nowcast_weight,
                    ensemble_mean, effective_std_scaled,
                    lo_c, hi_c,
                    temp_rate_c_per_h=temp_rate,
                )

    # 7. Calibration shrinkage correction.
    # When the model is overconfident (typical for NWP at short range), shrink
    # model_prob back toward 0.5 by the stored shrinkage factor before computing edge.
    # Factor is learned from resolved trade history and stored in kv_store.
    # Falls back to 1.0 (no correction) if not yet computed or < MIN_TRADES.
    raw_model_prob = final_model_prob
    try:
        from metrics.calibration import get_shrinkage_factor
        shrink = get_shrinkage_factor("temperature")
        if shrink != 1.0:
            final_model_prob = 0.5 + (raw_model_prob - 0.5) * shrink
            logger.debug("Cal shrinkage %.3f: %.3f → %.3f",
                         shrink, raw_model_prob, final_model_prob)
    except Exception:
        pass  # calibration module must never block a trade

    # 8. Edge (mid-price based, for display / logging)
    edge = final_model_prob - market_implied_prob
    direction = "YES" if final_model_prob > market_implied_prob else "NO"

    # Actual entry price: use real CLOB ask (YES entry) or 1-bid (NO entry) if available.
    # Mid-price overstates edge by ~half-spread; actual ask/bid is what we'd really pay.
    if direction == "YES":
        actual_entry = ask if ask is not None else market_implied_prob
    else:
        actual_entry = (1.0 - bid) if bid is not None else (1.0 - market_implied_prob)

    # Effective edge = what we'd actually earn above our true entry cost
    if direction == "YES":
        effective_edge = final_model_prob - actual_entry
    else:
        effective_edge = (1.0 - final_model_prob) - actual_entry

    # Skip YES bets on very low market prices — crowd has already priced these near zero
    # and the model's tiny edge is almost always noise (1.5% win rate observed in backtest)
    if direction == "YES" and market_implied_prob < 0.20:
        logger.debug("Skipping YES bet: market_price=%.3f < 0.20 — low-probability trap", market_implied_prob)
        return None

    # Skip YES bets with very low entry price — phantom leverage in thin markets.
    if direction == "YES" and actual_entry < 0.05:
        logger.debug("Skipping YES bet: actual_entry=%.4f < 0.05 — phantom leverage risk", actual_entry)
        return None

    # NO entry price gates — the sweet spot for NO bets is 20-75¢.
    # Below 20¢: market is pricing YES at >80% confidence. Our model has been
    #   consistently wrong when fighting this level of market consensus (0/4, -100% ROI).
    # Above 75¢: terrible risk/reward — we risk losing 75¢ to gain 25¢ max (33% ROI),
    #   and occasional blowups (-100%) make the expected value negative at this range.
    if direction == "NO":
        _no_entry = actual_entry if actual_entry > 0 else (1.0 - market_implied_prob)
        if _no_entry < NO_ENTRY_MIN_PRICE:
            logger.debug("Skipping NO bet: entry=%.4f < NO_ENTRY_MIN_PRICE=%.2f — market too confident in YES",
                         _no_entry, NO_ENTRY_MIN_PRICE)
            return None
        if _no_entry > NO_ENTRY_MAX_PRICE:
            logger.debug("Skipping NO bet: entry=%.4f > NO_ENTRY_MAX_PRICE=%.2f — poor risk/reward",
                         _no_entry, NO_ENTRY_MAX_PRICE)
            return None

        # Ensemble std gate: when all models tightly agree on temperature,
        # the specific bucket is likely to be hit — NO bets fail (29% WR below 0.8°C std).
        # Only applied to NO bets; YES bets may benefit from model consensus.
        if ensemble.get("std_c", 0.0) < NO_MIN_ENSEMBLE_STD:
            logger.debug(
                "Skipping NO bet: ensemble_std=%.2f < NO_MIN_ENSEMBLE_STD=%.2f — models in tight agreement, temp likely heading for specific bucket",
                ensemble.get("std_c", 0.0), NO_MIN_ENSEMBLE_STD,
            )
            return None

    # ── Dynamic MIN_EDGE ──────────────────────────────────────────────────────
    # Combines four factors:
    #   1. Base: nowcast override / lead-time penalty (existing logic)
    #   2. King Models conflict raises the bar (in addition to the 50% size cut)
    #   3. Spread floor: edge must exceed the bid-ask cost
    #   4. City reliability scalar from per-city Brier Skill Score

    # 1. Base
    if nowcast_weight > 0.7:
        # Same-day intraday confirmation — strong signal, lower bar
        adaptive_min_edge = 0.02
    elif lead_days <= MIN_EDGE_RECENT_DAYS:
        # Near-expiry: noisier forecasts and wider spreads empirically
        adaptive_min_edge = MIN_EDGE * MIN_EDGE_RECENT_MULTIPLIER
    else:
        adaptive_min_edge = MIN_EDGE

    # 2. King Models conflict: already cuts size 50%; also raise the edge bar
    #    so only high-conviction trades survive when the two best models disagree.
    if ensemble.get("king_conflict"):
        adaptive_min_edge *= 1.5

    # 3. Spread floor: entry must clear 1.5× the bid-ask spread.
    #    Prevents trades that look good on mid but lose to the cross.
    #    Most impactful on thin international markets (spreads 0.08–0.15).
    if bid is not None and ask is not None:
        spread = ask - bid
        if spread > 0:
            spread_floor = spread * 1.5
            if spread_floor > adaptive_min_edge:
                logger.debug("Spread floor %.3f overrides adaptive_min_edge %.3f (spread=%.3f)",
                             spread_floor, adaptive_min_edge, spread)
                adaptive_min_edge = spread_floor

    # 4. City reliability scalar from calibration Brier Skill Score (cached).
    #    BSS > 0.15 → proven outperformer → lower bar 15%.
    #    BSS < 0.0  → underperforming market → raise bar 30%.
    city_bss = _get_city_bss(city_name)
    if city_bss is not None:
        if city_bss > 0.15:
            adaptive_min_edge *= 0.85
            logger.debug("City BSS %.3f → lowering edge bar to %.3f", city_bss, adaptive_min_edge)
        elif city_bss < 0.0:
            adaptive_min_edge *= 1.30
            logger.debug("City BSS %.3f → raising edge bar to %.3f", city_bss, adaptive_min_edge)

    if abs(effective_edge) < adaptive_min_edge:
        logger.debug("Effective edge %.3f (entry=%.3f) below threshold %.3f — skip",
                     abs(effective_edge), actual_entry, adaptive_min_edge)
        return None

    # 8. Kelly sizing using actual entry price (more conservative than mid)
    bankroll = db.get_bankroll()
    p_win = final_model_prob if direction == "YES" else (1.0 - final_model_prob)

    # Filter: require minimum win probability after shrinkage.
    # NO trades: calibration shows 80-90% p_win bucket wins only 45.5% of the time.
    # YES trades: use a lower bar — 55%+ model confidence with >25¢ edge is tradeable.
    from config import MIN_WIN_PROB, MIN_WIN_PROB_YES
    threshold = MIN_WIN_PROB_YES if direction == "YES" else MIN_WIN_PROB
    if p_win < threshold:
        logger.debug("p_win %.3f below threshold %.3f (%s) — skip", p_win, threshold, direction)
        return None

    if actual_entry <= 0.001 or actual_entry >= 0.999:
        return None
    b_odds = (1.0 / actual_entry) - 1.0
    if b_odds <= 0:
        return None
    kf = max(0.0, (b_odds * p_win - (1.0 - p_win)) / b_odds)

    # Risk-management multipliers
    risk_mult = 1.0
    # High-conviction boost: when model diverges massively from market, allow larger bet
    if abs(edge) >= HIGH_CONVICTION_EDGE:
        risk_mult *= HIGH_CONVICTION_KELLY_MULT
    
    # King Models Conflict penalty: if ECMWF and GFS disagree wildly, cut bet by 50%
    if ensemble.get("king_conflict"):
        risk_mult *= 0.5
        logger.warning("Applying 50%% size penalty due to King Models Conflict")

    kf = min(kf * KF * risk_mult, 1.0)

    size_usdc = min(kf * bankroll, MAX_TRADE_FRACTION * bankroll)
    if size_usdc < 1.0:
        logger.debug("Kelly size %.2f too small — skip", size_usdc)
        return None

    # Boundary proximity penalty: when ensemble mean sits near a bucket edge,
    # the actual temperature has elevated odds of landing right at the boundary,
    # causing a loss on the adjacent NO bet. Halve size when within 40% of the
    # bucket width from either edge. This is especially common with 1°F buckets
    # (0.556°C wide) where F→C rounding frequently places actuals at exact edges.
    boundary_penalty = 1.0
    if lo_c is not None and hi_c is not None:
        bucket_width_c = hi_c - lo_c
        boundary_margin = 0.40 * bucket_width_c
        dist_lo = abs(ensemble["mean_c"] - lo_c)
        dist_hi = abs(ensemble["mean_c"] - hi_c)
        if min(dist_lo, dist_hi) < boundary_margin:
            boundary_penalty = 0.50
            size_usdc = round(size_usdc * boundary_penalty, 2)
            logger.info(
                "Boundary proximity penalty ×0.50: mean=%.2f°C bucket=[%.2f,%.2f)°C "
                "dist_lo=%.3f dist_hi=%.3f margin=%.3f → size=$%.2f",
                ensemble["mean_c"], lo_c, hi_c, dist_lo, dist_hi, boundary_margin, size_usdc,
            )

    entry_price = actual_entry

    return {
        "direction":            direction,
        "entry_price":          entry_price,
        "model_prob":           round(final_model_prob, 4),
        "base_model_prob":      round(base_prob, 4),
        "market_prob":          round(market_implied_prob, 4),
        "edge":                 round(edge, 4),
        "effective_edge":       round(effective_edge, 4),
        "ensemble_mean_c":      round(ensemble["mean_c"], 2),
        "ensemble_std_c":       round(ensemble["std_c"], 2),
        "effective_std":        round(effective_std_scaled, 2),
        "horizon_scale":        round(horizon_scale, 3),
        "lead_days":            lead_days,
        "ensemble_score":       ensemble["score"],
        "n_models":             ensemble["n_models"],
        "size_usdc":            round(size_usdc, 2),
        "kelly_f":              round(kf, 4),
        "nowcast_weight":       round(nowcast_weight, 3),
        "running_max_c":        running_max,
        "running_max_sources":  sources,
        "bucket_lo_c":          lo_c,
        "bucket_hi_c":          hi_c,
        "target_date":          target_date,
        "climo_mean_c":         climo_mean_c,
        "climo_deviation_c":    climo_deviation_c,
        "climo_std_c":          climo_std_c,
        "anchor_divergence_c":  anchor_divergence_c,
        "has_climo":            climo is not None,
        "king_conflict":        ensemble.get("king_conflict", False),
        "adaptive_min_edge":    round(adaptive_min_edge, 4),
        "boundary_penalty":     boundary_penalty,
    }
