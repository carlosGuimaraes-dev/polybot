"""
Wunderground data fetcher — PRIMARY resolution source for most cities.

Resolution source priority (broker/position_manager.py):
  1. Wunderground — Polymarket's stated resolution source for most cities
  2. Iowa State ASOS — official airport obs (fallback, primary for Tel Aviv)
  3. Open-Meteo Archive — ERA5 reanalysis (last resort)

WU is also used for live intraday obs in the nowcaster (advisory only).
"""
import re
import json
import logging
import time
import requests
from datetime import date, datetime

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.wunderground.com/",
}

TIMEOUT = 20


class WundergroundError(Exception):
    pass


_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = [2, 4]  # seconds between attempts (3 total attempts)


def _fetch_wu_page(icao: str, target_date: str) -> str:
    """Fetch raw HTML of the WU history page for an ICAO station and date.

    Retries up to 3 attempts with exponential backoff (2s, 4s) on transient
    errors: HTTP 429/500/502/503/504, ConnectionError, and Timeout.
    """
    url = f"https://www.wunderground.com/history/daily/{icao}/date/{target_date}"
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.debug("WU retry %d/%d for %s %s (backoff %ds)",
                         attempt + 1, len(_RETRY_DELAYS) + 1, icao, target_date, delay)
            time.sleep(delay)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            logger.debug("WU ConnectionError (attempt %d): %s", attempt + 1, e)
        except requests.exceptions.Timeout as e:
            last_exc = e
            logger.debug("WU Timeout (attempt %d): %s", attempt + 1, e)
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if e.response is not None and e.response.status_code in _RETRY_STATUS_CODES:
                logger.debug("WU HTTP %d (attempt %d): %s",
                             e.response.status_code, attempt + 1, e)
            else:
                raise WundergroundError(
                    f"WU page fetch failed for {icao} {target_date}: {e}"
                ) from e
        except requests.RequestException as e:
            raise WundergroundError(
                f"WU page fetch failed for {icao} {target_date}: {e}"
            ) from e
    raise WundergroundError(
        f"WU page fetch failed for {icao} {target_date} after "
        f"{len(_RETRY_DELAYS) + 1} attempts: {last_exc}"
    )


# ── TWC JSON API (the data source the WU page itself calls) ──────────────────
# Since ~2026-09 WU's history page serves a React shell without embedded
# observations (client-side XHR only). The page's JS calls api.weather.com
# directly with a public apiKey injected into the page shell — we call the
# same endpoint. Verified working 2026-09-06 for US + international stations,
# today and past dates, metric units.
_TWC_API_BASE = "https://api.weather.com"
_TWC_API_KEY = "f6d2efe5720d47ea92efe5720df7eaa8"  # public key from WU page shell

# ICAO → ISO country code for the v1 location key format `{icao}:9:{cc}`.
# Every entry verified against the API on 2026-09-06 (36/37 direct hits).
_STATION_COUNTRY = {
    "KLGA": "US", "KORD": "US", "KATL": "US", "KMIA": "US", "KDAL": "US",
    "KSEA": "US", "KHOU": "US", "KLAX": "US", "KDEN": "US", "KAUS": "US",
    "KSFO": "US",
    "EGLL": "GB", "LFPG": "FR", "LEMD": "ES", "EDDM": "DE", "LIMC": "IT",
    "VHHH": "HK", "CYYZ": "CA", "SAEZ": "AR", "SBGR": "BR", "LLBG": "IL",
    "RKSS": "KR", "RJTT": "JP", "WSSS": "SG",
    "ZBAA": "CN", "ZSPD": "CN", "ZGSZ": "CN", "ZHHH": "CN", "ZUUU": "CN",
    "ZUCK": "CN",
    "RCTP": "TW", "VILK": "IN", "LTAC": "TR", "EPWA": "PL", "LTFM": "TR",
    "NZWN": "NZ", "MMMX": "MX",
    "LTBA": "TR",   # alias target for LTFM (see _STATION_ALIAS)
}

# LTFM (Istanbul New Airport) is absent from TWC's v1 station database.
# LTBA (Atatürk, ~35km away) is the closest substitute — fine for advisory
# nowcasting; market resolution should rely on ASOS/ERA5 first anyway.
_STATION_ALIAS = {"LTFM": "LTBA"}


def _twc_location_key(icao: str) -> str:
    """Build the TWC v1 location key `{icao}:9:{cc}` for a station."""
    lookup = _STATION_ALIAS.get(icao, icao)
    cc = _STATION_COUNTRY.get(lookup)
    if not cc:
        raise WundergroundError(f"No country code mapped for {icao} — TWC API unavailable")
    return f"{lookup}:9:{cc}"


def _twc_fetch_observations(icao: str, start_date: str, end_date: str) -> list[dict]:
    """
    Fetch observations from the TWC v1 historical endpoint (same source the
    WU page calls). Dates as YYYYMMDD. Returns raw obs dicts
    ({valid_time_gmt: epoch_s, temp: °C metric, ...}).
    Raises WundergroundError on failure.
    """
    url = (f"{_TWC_API_BASE}/v1/location/{_twc_location_key(icao)}/observations/"
           f"historical.json?apiKey={_TWC_API_KEY}&units=m"
           f"&startDate={start_date}&endDate={end_date}")
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=TIMEOUT)
            if resp.status_code == 400:
                # invalid location/date — not transient, don't retry
                raise WundergroundError(
                    f"TWC API rejected request for {icao} ({start_date}-{end_date}): "
                    f"{resp.text[:120]}"
                )
            resp.raise_for_status()
            obs = resp.json().get("observations")
            if obs is None:
                raise WundergroundError(f"TWC response missing observations for {icao}")
            return obs
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            last_exc = e
    raise WundergroundError(f"TWC API fetch failed for {icao}: {last_exc}")


def _twc_daily_high(icao: str, target_date: str) -> float:
    """Daily high (°C) for target_date ('YYYY-MM-DD') from the TWC API."""
    ymd = target_date.replace("-", "")
    obs = _twc_fetch_observations(icao, ymd, ymd)
    temps = [float(o["temp"]) for o in obs if o.get("temp") is not None]
    if not temps:
        raise WundergroundError(f"No temperatures in TWC response for {icao} {target_date}")
    return max(temps)


def _extract_json_blob(html: str) -> dict | None:
    """
    WU embeds its React state in the largest <script> tag as a JSON blob.
    Try to extract temperature observations from it.
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    if not scripts:
        return None
    big = max(scripts, key=len)
    try:
        data = json.loads(big)
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def _walk(obj, key, depth=0):
    """Recursively search for a key in a nested dict/list."""
    if depth > 10:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _walk(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj[:20]:
            r = _walk(item, key, depth + 1)
            if r is not None:
                return r
    return None


def _parse_daily_high_from_blob(data: dict) -> float | None:
    """
    Navigate the WU JSON blob to find the daily high temperature in °C.
    WU stores metric values under 'metric' sub-objects.
    """
    # Try multiple known paths
    for high_key in ["tempHigh", "maxTemp", "high", "maxTempAvg"]:
        val = _walk(data, high_key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    # Try to find hourly obs and compute max
    obs = _walk(data, "observations")
    if obs and isinstance(obs, list) and len(obs) > 1:
        temps = []
        for o in obs:
            # Try metric temp first, then imperial
            t = None
            metric = o.get("metric") or {}
            if "temp" in metric:
                t = metric["temp"]
            elif "tempAvg" in metric:
                t = metric["tempAvg"]
            else:
                imperial = o.get("imperial") or {}
                if "temp" in imperial:
                    try:
                        t = (float(imperial["temp"]) - 32) * 5 / 9  # F → C
                    except (TypeError, ValueError):
                        pass
            if t is not None:
                try:
                    temps.append(float(t))
                except (TypeError, ValueError):
                    pass
        if temps:
            return max(temps)

    return None


def get_historical_high(icao: str, target_date: str) -> float:
    """
    Fetch the daily recorded high temperature (°C) from Wunderground.
    target_date: 'YYYY-MM-DD'
    Raises WundergroundError if unavailable or parsing fails.
    """
    # Primary: TWC JSON API (the WU page no longer embeds obs in its HTML)
    try:
        high = _twc_daily_high(icao, target_date)
        logger.info("WU/TWC %s %s: daily high = %.1f°C", icao, target_date, high)
        return high
    except WundergroundError as e:
        logger.warning("TWC API unavailable for %s %s (%s) — falling back to HTML page",
                       icao, target_date, e)

    html = _fetch_wu_page(icao, target_date)
    blob = _extract_json_blob(html)

    if blob:
        high = _parse_daily_high_from_blob(blob)
        if high is not None:
            logger.info("WU %s %s: daily high = %.1f°C", icao, target_date, high)
            return high

    # Attempt regex extraction from raw HTML as last resort
    # Look for the summary table values
    patterns = [
        r'"tempHigh"\s*:\s*(-?\d+\.?\d*)',
        r'"maxTemp"\s*:\s*(-?\d+\.?\d*)',
        r'"highTemp"\s*:\s*(-?\d+\.?\d*)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            val = float(m.group(1))
            logger.info("WU %s %s: regex extracted %.1f°C", icao, target_date, val)
            return val

    raise WundergroundError(
        f"Could not extract daily high from WU page for {icao} {target_date}. "
        f"Page may require JS rendering."
    )


def get_live_hourly(icao: str) -> list[dict]:
    """
    Fetch today's hourly observations (°C) for an ICAO station.
    Primary source: TWC JSON API (same endpoint the WU page calls).
    Fallback: legacy WU HTML page parsing (no longer served with data).
    Returns list of {time_local, temp_c} sorted by time.
    Raises WundergroundError if unavailable.
    """
    today = date.today()
    today_ymd = today.strftime("%Y%m%d")
    try:
        obs = _twc_fetch_observations(icao, today_ymd, today_ymd)
    except WundergroundError as e:
        logger.warning("TWC live obs failed for %s (%s) — falling back to HTML page",
                       icao, e)
        return _get_live_hourly_html(icao)

    hourly = []
    for o in obs:
        if o.get("temp") is None:
            continue
        try:
            ts = int(o.get("valid_time_gmt") or 0)
            t = float(o["temp"])
        except (TypeError, ValueError):
            continue
        # Keep only the machine-local calendar day (parity with the old page-based
        # behavior) so the previous day's evening temps don't inflate the max.
        if datetime.fromtimestamp(ts).date() != today:
            continue
        hourly.append({"time_local": str(ts), "temp_c": t})

    if not hourly:
        raise WundergroundError(f"Parsed 0 hourly observations for {icao} today")

    return sorted(hourly, key=lambda x: x["time_local"])


def _get_live_hourly_html(icao: str) -> list[dict]:
    """
    Legacy path: parse today's hourly obs out of the WU HTML page.
    Kept as fallback in case the TWC API is unreachable. The page has served
    a data-less React shell since ~2026-09, so this usually raises.
    """
    today_str = date.today().isoformat()
    html = _fetch_wu_page(icao, today_str)
    blob = _extract_json_blob(html)

    if not blob:
        raise WundergroundError(f"Could not parse WU JSON for {icao} today")

    obs = _walk(blob, "observations")
    if not obs or not isinstance(obs, list):
        raise WundergroundError(f"No observations in WU response for {icao} today")

    hourly = []
    for o in obs:
        t = None
        time_local = o.get("obsTimeLocal") or o.get("valid_time_gmt", "")

        metric = o.get("metric") or {}
        if "temp" in metric:
            t = metric["temp"]
        elif "tempAvg" in metric:
            t = metric["tempAvg"]
        else:
            imperial = o.get("imperial") or {}
            if "temp" in imperial:
                try:
                    t = (float(imperial["temp"]) - 32) * 5 / 9
                except (TypeError, ValueError):
                    pass

        if t is not None:
            try:
                hourly.append({"time_local": str(time_local), "temp_c": float(t)})
            except (TypeError, ValueError):
                pass

    if not hourly:
        raise WundergroundError(f"Parsed 0 hourly observations for {icao} today")

    return sorted(hourly, key=lambda x: x["time_local"])


def get_running_max_wu(icao: str) -> float | None:
    """
    Get today's running maximum temperature from WU.
    Returns max temp in °C, or None if WU is unavailable.
    Does NOT raise — live obs are optional (METAR is the primary live source).
    """
    try:
        hourly = get_live_hourly(icao)
        if hourly:
            return max(o["temp_c"] for o in hourly)
        return None
    except WundergroundError as e:
        logger.warning("WU live obs unavailable for %s: %s", icao, e)
        return None
