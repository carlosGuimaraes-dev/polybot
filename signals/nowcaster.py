"""
Mid-day nowcaster.

After 2pm local city time:
  - Pull live METAR + ASOS for today
  - If WU and METAR disagree by > 2°C → flag as uncertain
  - Track running maximum temperature
  - Weight: 0.0 at noon, 0.5 at 2pm, 0.95 at 4pm (linear)
  - If running_max is already outside the crowd's top 2 buckets → near-certain trade

The nowcast confidence weight blends in with the model probability:
  blended_prob = (1 - weight) * model_prob + weight * nowcast_prob
"""
import logging
import math
from datetime import datetime, date
import pytz
from config import CITIES, ASOS_RESOLUTION_CITIES
from data.noaa import get_running_max_today, fetch_metar
from data.wunderground import get_running_max_wu

logger = logging.getLogger(__name__)


def _local_hour(timezone_str: str) -> float:
    """Current local hour (fractional) in the given timezone."""
    tz = pytz.timezone(timezone_str)
    now_local = datetime.now(tz)
    return now_local.hour + now_local.minute / 60.0


def nowcast_confidence(timezone_str: str) -> float:
    """
    Returns a confidence weight [0, 1] based on local time.
    0.0 before noon, linearly rising from 0.5 at 2pm to 0.95 at 4pm.
    """
    hour = _local_hour(timezone_str)
    if hour < 12.0:
        return 0.0
    if hour < 14.0:
        # Ramp 0 → 0.5 between noon and 2pm
        return 0.5 * (hour - 12.0) / 2.0
    if hour < 16.0:
        # Ramp 0.5 → 0.95 between 2pm and 4pm
        return 0.5 + 0.45 * (hour - 14.0) / 2.0
    return 0.95


def get_running_max_c(city_name: str) -> tuple[float | None, float | None, dict]:
    """
    Get today's running max temperature and temperature trend for a city.

    Returns (running_max_c, temp_rate_c_per_h, sources).
      running_max_c     — highest temperature observed so far today (°C), or None
      temp_rate_c_per_h — rate of change over last ~2h (°C/h), or None if < 3 obs
      sources           — {"metar_c": ..., "asos_c": ..., "wu_c": ...} raw values,
                          logged into scan_log for post-mortems

    Merge priority follows Polymarket's resolution source
    (config.ASOS_RESOLUTION_CITIES): most cities resolve on Wunderground, so
    the WU reading is primary there; Tel Aviv resolves on ASOS/NOAA. The other
    sources are cross-checks only — divergence is logged, never merged via
    max() (a max() merge let a transient reading manufacture a fake NO edge
    in Atlanta on 2026-09-07).
    """
    cfg = CITIES.get(city_name)
    if not cfg:
        return None, None, {}
    icao = cfg["icao"]
    asos = cfg["asos_station"]
    tz   = cfg["timezone"]

    # 1. Collect every source raw — no merging yet
    metar_temp = None
    try:
        metar_data = fetch_metar([icao])
        if icao in metar_data:
            metar_temp = metar_data[icao]["temp_c"]
    except Exception as e:
        logger.warning("METAR fetch failed for %s: %s", icao, e)

    asos_max = None
    rate = None
    asos_result = get_running_max_today(asos, tz)
    if asos_result:
        asos_max = asos_result["running_max_c"]
        rate = asos_result.get("temp_rate_c_per_h")

    wu_temp = get_running_max_wu(icao)

    sources = {"metar_c": metar_temp, "asos_c": asos_max, "wu_c": wu_temp}
    logger.info("Nowcast sources %s: metar=%s asos=%s wu=%s",
                city_name, metar_temp, asos_max, wu_temp)

    # 2. Merge with the resolution-aligned source as primary
    if city_name in ASOS_RESOLUTION_CITIES:
        candidates = [v for v in (metar_temp, asos_max) if v is not None]
        running_max = max(candidates) if candidates else wu_temp
    elif wu_temp is not None:
        # WU is Polymarket's resolution source for this city
        running_max = wu_temp
        others = [v for v in (metar_temp, asos_max) if v is not None]
        # Flag only when WU is the odd one out (diverges from every other source);
        # a single outlier METAR next to two agreeing sources is not a WU problem.
        if others and all(abs(wu_temp - v) > 2.0 for v in others):
            logger.warning(
                "%s: WU (%.1f°C) is the outlier vs METAR/ASOS %s — "
                "keeping WU (resolution source) but flagging",
                city_name, wu_temp, others
            )
    else:
        candidates = [v for v in (metar_temp, asos_max) if v is not None]
        running_max = max(candidates) if candidates else None

    return running_max, rate, sources


def compute_nowcast_bucket_prob(
    running_max_c: float,
    confidence: float,
    ensemble_mean_c: float,
    ensemble_effective_std: float,
    bucket_lo_c: float | None,
    bucket_hi_c: float | None,
    temp_rate_c_per_h: float | None = None,
) -> float:
    """
    Blend the model probability with the nowcast observation.

    Strategy: as the day progresses, the running max provides an increasingly
    strong lower bound on the final daily max. We model the final max as:
        final_max ~ max(running_max, t(ensemble_mean, effective_std))
    which we approximate as:
        P(bucket | running_max) ∝ original_prob re-weighted by the observation

    temp_rate_c_per_h: temperature trend from recent ASOS hourly obs.
        < -0.5°C/h  → clearly past peak → boost confidence toward running_max
        > +1.5°C/h  → still warming fast → trust model residual more (reduce confidence)
        Otherwise   → no adjustment
    """
    # Adjust confidence based on temperature trend (rate-of-change)
    if temp_rate_c_per_h is not None:
        if temp_rate_c_per_h < -0.5:
            # Temperature is falling — running_max is almost certainly the day's high
            confidence = min(0.99, confidence + 0.20)
            logger.debug("Rate %.2f°C/h (falling) → confidence boosted to %.2f",
                         temp_rate_c_per_h, confidence)
        elif temp_rate_c_per_h > 1.5:
            # Still warming fast — model's residual upside is plausible
            confidence = max(0.0, confidence - 0.15)
            logger.debug("Rate %.2f°C/h (rising fast) → confidence reduced to %.2f",
                         temp_rate_c_per_h, confidence)

    from scipy.stats import t as _t
    from config import FORECAST_T_DF

    # Convert bucket to °C if needed (caller handles unit conversion before calling)
    lo = bucket_lo_c if bucket_lo_c is not None else -999.0
    hi = bucket_hi_c if bucket_hi_c is not None else 999.0

    # Model probability — Student's t for fat-tail consistency with edge_calculator
    model_prob = _t.cdf(hi, FORECAST_T_DF, loc=ensemble_mean_c, scale=ensemble_effective_std) - \
                 _t.cdf(lo, FORECAST_T_DF, loc=ensemble_mean_c, scale=ensemble_effective_std)

    if confidence < 0.05:
        return model_prob

    # ── Hard boundary constraints ──────────────────────────────────────────────
    # daily_max ≥ running_max is a physical certainty (you can't un-observe a temp).
    # When the observation definitively settles the outcome, bypass the soft blend.
    #
    # METAR/ASOS sensors can read 0.5–1°C warmer than the temperature source
    # Polymarket uses for resolution (e.g. airport tarmac vs nearby AWS). A 1°C
    # margin prevents premature hard-zeros caused by this sensor offset.
    _HARD_ZERO_MARGIN_C = 1.0  # °C above bucket_hi before declaring YES impossible

    # Observed max vs bucket ceiling — the sensor margin applies consistently:
    #  - running_max ≥ bucket_hi + margin → YES is impossible (hard zero)
    #  - running_max within the margin above bucket_hi → can't be sure the
    #    bucket was truly exceeded (sensors can over-read); defer to the
    #    unconditioned model instead of clamping to zero. Clamping here
    #    manufactured a fake NO edge in Atlanta on 2026-09-07 (observed
    #    running max 84.0°F vs true daily max 82°F).
    if bucket_hi_c is not None and running_max_c > bucket_hi_c:
        if running_max_c >= bucket_hi_c + _HARD_ZERO_MARGIN_C:
            logger.debug(
                "Nowcast hard-zero: running_max=%.1f >= bucket_hi=%.1f + margin=%.1f — YES impossible",
                running_max_c, bucket_hi_c, _HARD_ZERO_MARGIN_C,
            )
            return 0.0
        logger.debug(
            "Nowcast margin zone: running_max=%.1f within %.1f°C of bucket_hi=%.1f — "
            "using unconditioned model prob",
            running_max_c, _HARD_ZERO_MARGIN_C, bucket_hi_c,
        )
        return model_prob

    # Case 2: running_max ≥ bucket_lo and bucket has no ceiling (≥X markets) →
    #   YES is already guaranteed (the daily high has hit the threshold).
    if bucket_hi_c is None and bucket_lo_c is not None and running_max_c >= bucket_lo_c:
        logger.debug(
            "Nowcast hard-one: running_max=%.1f >= bucket_lo=%.1f — YES guaranteed",
            running_max_c, bucket_lo_c,
        )
        return 1.0

    # Nowcast lower bound: the final max must be >= running_max
    # P(final_max in [lo, hi] | final_max >= running_max)
    # = P(running_max <= final_max < hi) / P(final_max >= running_max)
    effective_lo = max(lo, running_max_c)
    p_above_running = 1.0 - _t.cdf(running_max_c, FORECAST_T_DF, loc=ensemble_mean_c, scale=ensemble_effective_std)
    if p_above_running < 1e-9:
        # Running max is already way above the distribution
        return 0.0

    nowcast_prob = (
        _t.cdf(hi, FORECAST_T_DF, loc=ensemble_mean_c, scale=ensemble_effective_std) -
        _t.cdf(effective_lo, FORECAST_T_DF, loc=ensemble_mean_c, scale=ensemble_effective_std)
    ) / p_above_running

    nowcast_prob = max(0.0, min(1.0, nowcast_prob))
    blended = (1.0 - confidence) * model_prob + confidence * nowcast_prob

    logger.debug(
        "Nowcast: running_max=%.1f  model_prob=%.3f  nowcast_prob=%.3f  "
        "confidence=%.2f  blended=%.3f",
        running_max_c, model_prob, nowcast_prob, confidence, blended
    )
    return blended
