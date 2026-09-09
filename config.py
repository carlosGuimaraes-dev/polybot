"""
City and station configuration.
Only cities that actually have active temperature markets on Polymarket are included.
ICAO codes confirmed against Iowa State Mesonet ASOS coverage.
"""

# Open-Meteo model endpoints — queried separately to keep forecasts independent
OPENMETEO_MODELS = {
    "gfs":         "https://api.open-meteo.com/v1/gfs",
    "ecmwf":       "https://api.open-meteo.com/v1/ecmwf",
    "icon":        "https://api.open-meteo.com/v1/dwd-icon",
    "gem":         "https://api.open-meteo.com/v1/gem",
    "meteofrance": "https://api.open-meteo.com/v1/meteofrance",
    # HRRR: CONUS-only, hourly cycles, 3km resolution — best short-range US model
    "hrrr":        "https://api.open-meteo.com/v1/forecast",
}

# Extra query params required by specific models (merged into the standard params dict)
OPENMETEO_MODEL_PARAMS: dict[str, dict] = {
    "hrrr": {"models": "hrrr"},
}

# HRRR coverage: Continental US only (roughly).
# Fetches outside these bounds are skipped automatically.
HRRR_LAT_MIN, HRRR_LAT_MAX =  20.0,  55.0
HRRR_LON_MIN, HRRR_LON_MAX = -135.0, -60.0

# Open-Meteo archive endpoint (ERA5 reanalysis — used as historical actuals)
OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo climate API (30-year WMO climatological baselines)
CLIMATE_API_URL = "https://climate-api.open-meteo.com/v1/climate"

# Iowa State Mesonet ASOS (hourly station obs, free, no auth)
ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# NOAA Aviation Weather METAR (live, free, no auth)
METAR_URL = "https://aviationweather.gov/api/data/metar"

# Polymarket Gamma API
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

# Trading thresholds
MIN_EDGE             = 0.18   # EXPERIMENT (2026-09-06, paper only): lowered from 0.25 to
                              # collect resolved-trade evidence for the 0.18-0.25 band. Prior evidence:
                              # 0.12-0.20 band had 19% win rate — expect this to underperform; revert
                              # to 0.25 if band win rate < 70% or ROI negative after ~20 resolved trades.
                              # Do NOT deploy this value to the live host.
MIN_WIN_PROB         = 0.90   # min p_win for NO trades after shrinkage — filters bad 80-90% confidence bucket (45.5% actual win rate)
MIN_WIN_PROB_YES     = 0.55   # min model_prob for YES trades — lower bar since YES = model predicts the bucket
NO_ENTRY_MIN_PRICE   = 0.20   # don't buy NO below 20¢ — market too confident in YES, model loses this fight (0/4 live, -100% ROI)
NO_ENTRY_MAX_PRICE   = 0.75   # don't buy NO above 75¢ — terrible risk/reward (2-10% ROI), occasional -100% blowup
NO_MIN_ENSEMBLE_STD  = 0.8    # skip NO bets when models agree tightly — low std means temp heading for a specific bucket (29-38% WR below 0.8°C)
ENSEMBLE_STD_MIN     = 0.5    # °C — models must disagree at least this much
ENSEMBLE_STD_MAX     = 2.0    # °C — skip if models are too chaotic
MIN_HISTORY_DAYS     = 14     # days of obs needed before trading a station
KELLY_FRACTION       = 0.10   # conservative for live trading (was 0.25 in paper)
MAX_TRADE_FRACTION   = 0.08   # max single trade = 8% of current bankroll
MAX_TRADE_USDC       = 15.0   # hard dollar cap per trade — prevents huge bets when bankroll grows
STARTING_BANKROLL    = 1000.0
MAX_DEPLOYED_FRACTION    = 0.60   # max fraction of total portfolio in open positions (was 0.90)
MAX_CITY_DATE_FRACTION   = 0.15   # max total deployed for one city+date (limits correlated loss exposure)
MIN_MARKET_VOLUME_USDC   = 500.0  # skip markets with lifetime volume below this — thin books mean wide spreads and our order would move the price

# Opportunistic 30-minute scan guards (to avoid overtrading/noisy churn)
OPPORTUNISTIC_MIN_FREE_BANKROLL_USDC = 25.0   # skip opportunistic scans if free bankroll is below this
OPPORTUNISTIC_COOLDOWN_MINUTES       = 20     # minimum spacing between opportunistic scan runs
OPPORTUNISTIC_MIN_MARKETS            = 8      # skip if too few tradeable markets are live
OPPORTUNISTIC_MAX_OPEN_TRADES        = 80     # cap: no new opportunistic scan when book is already very full

# High-conviction override: when model_prob diverges from market by this much,
# allow up to 2× normal Kelly (still capped by MAX_TRADE_FRACTION)
HIGH_CONVICTION_EDGE     = 0.30   # e.g. model=0.90 vs market=0.60
HIGH_CONVICTION_KELLY_MULT = 2.0

# Forecast uncertainty to add when building the Gaussian
# (accounts for systematic errors not captured by model spread alone)
BASE_FORECAST_STD_C  = 2.00   # °C added in quadrature to ensemble spread

# Persistence Alpha: blend in short-term (last 7 days) bias.
# 0.3 means 30% of the bias comes from the last week, 70% from the long-term monthly mean.
# This helps the bot adapt to heatwaves or cold snaps the global models miss.
PERSISTENCE_BIAS_WEIGHT = 0.35   # (was 0.0 initially, now active)
MIN_PERSISTENCE_DAYS    = 3      # need at least 3 days of recent data to apply persistence

# King Models Conflict: disagreement between ECMWF and GFS.
# If these two disagree by more than this threshold, we cut bet size by 50%.
KING_CONFLICT_MAX_C     = 3.5    # °C

# Neighbor validation: reference coordinates ~25-30km from each city in flat,
# climatologically similar terrain. A single GFS fetch at the reference point
# is compared to the city's ensemble mean. If they diverge by more than
# NEIGHBOR_DIVERGENCE_C, a model grid artifact is likely and size is penalized.
NEIGHBOR_REFS = {
    # US — offsets stay on the same coastal plain / continental basin
    "New York City": {"lat": 40.55,  "lon": -73.87},   # 25km south of LGA
    "Chicago":       {"lat": 42.20,  "lon": -87.90},   # 25km north of ORD
    "Miami":         {"lat": 25.55,  "lon": -80.29},   # 25km south of MIA
    "Dallas":        {"lat": 33.07,  "lon": -96.85},   # 25km north of DAL
    "Atlanta":       {"lat": 33.86,  "lon": -84.43},   # 25km north of ATL
    "Houston":       {"lat": 30.22,  "lon": -95.34},   # 25km north of HOU
    "Los Angeles":   {"lat": 34.18,  "lon": -118.41},  # 25km north of LAX
    "Denver":        {"lat": 40.08,  "lon": -104.67},  # 25km north of DEN (flat plains)
    "Austin":        {"lat": 30.44,  "lon": -97.67},   # 25km north of AUS
    # Asia
    "Hong Kong":     {"lat": 22.64,  "lon": 113.81},   # Shenzhen ZGSZ (~30km north)
    "Tokyo":         {"lat": 35.76,  "lon": 139.78},   # 25km north, Kanto plain
    "Singapore":     {"lat": 1.56,   "lon": 103.99},   # 25km north into Johor
    "Beijing":       {"lat": 40.30,  "lon": 116.60},   # 25km north
    "Shanghai":      {"lat": 31.38,  "lon": 121.80},   # 25km north
    # Skip: Seattle (Puget Sound fog), SF (coastal fog), cities crossing mountain ranges
}
NEIGHBOR_DIVERGENCE_C   = 3.0   # °C — divergence above this triggers the penalty
NEIGHBOR_PENALTY_MULT   = 0.5   # cut size by 50% when a grid artifact is suspected

# Fat-tail distribution for bucket probability.
# Weather extremes have heavier tails than Gaussian — Student's t with low df
# prevents the bot from under-pricing extreme outlier buckets.
# df=4 gives tails ~3× heavier than Gaussian beyond 2σ. Tropical/coastal cities
# (Singapore, Miami) are closer to Gaussian but df=4 errs conservatively for all.
FORECAST_T_DF           = 4
                               # Recalibrated 2026-03-25: was 0.90 which gave peak bucket P=42%
                               # — far too high vs actual YES rate of 8-15% per 1°C bucket.
                               # At std=2.00, peak bucket P≈20%, matching empirical resolution rate.
                               # Prior value 0.90 caused YES bets to win only 48-67% (near coin flip).

# Minimum edge multiplier for very recent markets (resolving within 7 days)
MIN_EDGE_RECENT_MULTIPLIER = 1.5   # require 1.5× MIN_EDGE for lead_days <= 7
MIN_EDGE_RECENT_DAYS       = 7

# Per-city additive forecast bias corrections (°C added to ensemble mean).
# Applied on top of per-model bias corrections for cities where ASOS data is
# unavailable (international stations) or where systematic grid-point mismatch exists.
# Positive = model runs cold vs reality, Negative = model runs warm.
CITY_FORECAST_BIAS_C = {
    "Hong Kong": 1.81,   # VHHH: no ASOS, ERA5 grid runs cold vs HKIA obs (-1.81°C mean err)
}

# How many days of history to backfill
BACKFILL_DAYS        = 180

# Cities where Polymarket resolves via ASOS/NOAA instead of Wunderground.
# All other cities resolve on Wunderground — single source of truth shared by
# position_manager (resolution) and nowcaster (live-obs merge priority).
ASOS_RESOLUTION_CITIES = {"Tel Aviv"}

# ── City configurations ───────────────────────────────────────────────────────
# icao         : 4-char ICAO airport station code (Wunderground + ASOS identifier)
# lat / lon    : coordinates for Open-Meteo forecast queries
# timezone     : pytz-compatible name (for nowcast timing)
# uses_fahrenheit: True for US cities (Polymarket quotes in °F), False = °C
# asos_station : station code as used by Iowa State ASOS (usually same as icao,
#                but US 3-char codes drop the leading 'K')

CITIES = {
    "New York City": {
        "icao":             "KLGA",
        "asos_station":     "LGA",
        "lat":              40.78,
        "lon":             -73.87,
        "timezone":         "America/New_York",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KLGA/date/",
    },
    "Chicago": {
        "icao":             "KORD",
        "asos_station":     "ORD",
        "lat":              41.98,
        "lon":             -87.90,
        "timezone":         "America/Chicago",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KORD/date/",
    },
    "Atlanta": {
        "icao":             "KATL",
        "asos_station":     "ATL",
        "lat":              33.64,
        "lon":             -84.43,
        "timezone":         "America/New_York",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KATL/date/",
    },
    "Miami": {
        "icao":             "KMIA",
        "asos_station":     "MIA",
        "lat":              25.79,
        "lon":             -80.29,
        "timezone":         "America/New_York",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KMIA/date/",
    },
    "Dallas": {
        "icao":             "KDAL",   # Love Field — matches Polymarket's resolution station
        "asos_station":     "DAL",
        "lat":              32.847,
        "lon":             -96.851,
        "timezone":         "America/Chicago",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KDAL/date/",
    },
    "Seattle": {
        "icao":             "KSEA",
        "asos_station":     "SEA",
        "lat":              47.46,
        "lon":            -122.31,
        "timezone":         "America/Los_Angeles",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KSEA/date/",
    },
    "London": {
        "icao":             "EGLL",
        "asos_station":     "EGLL",
        "lat":              51.48,
        "lon":             -0.45,
        "timezone":         "Europe/London",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/EGLL/date/",
    },
    "Paris": {
        "icao":             "LFPG",
        "asos_station":     "LFPG",
        "lat":              49.01,
        "lon":              2.55,
        "timezone":         "Europe/Paris",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LFPG/date/",
    },
    "Madrid": {
        "icao":             "LEMD",
        "asos_station":     "LEMD",
        "lat":              40.47,
        "lon":             -3.57,
        "timezone":         "Europe/Madrid",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LEMD/date/",
    },
    "Munich": {
        "icao":             "EDDM",
        "asos_station":     "EDDM",
        "lat":              48.35,
        "lon":             11.79,
        "timezone":         "Europe/Berlin",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/EDDM/date/",
    },
    "Milan": {
        "icao":             "LIMC",
        "asos_station":     "LIMC",
        "lat":              45.63,
        "lon":              8.72,
        "timezone":         "Europe/Rome",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LIMC/date/",
    },
    "Hong Kong": {
        "icao":             "VHHH",
        "asos_station":     "VHHH",
        "lat":              22.31,
        "lon":             113.92,
        "timezone":         "Asia/Hong_Kong",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/VHHH/date/",
    },
    "Toronto": {
        "icao":             "CYYZ",
        "asos_station":     "CYYZ",
        "lat":              43.68,
        "lon":             -79.63,
        "timezone":         "America/Toronto",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/CYYZ/date/",
    },
    "Buenos Aires": {
        "icao":             "SAEZ",
        "asos_station":     "SAEZ",
        "lat":             -34.82,
        "lon":             -58.54,
        "timezone":         "America/Argentina/Buenos_Aires",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/SAEZ/date/",
    },
    "Sao Paulo": {
        "icao":             "SBGR",
        "asos_station":     "SBGR",
        "lat":             -23.43,
        "lon":             -46.47,
        "timezone":         "America/Sao_Paulo",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/SBGR/date/",
    },
    "Tel Aviv": {
        "icao":             "LLBG",
        "asos_station":     "LLBG",
        "lat":              31.99,
        "lon":             34.90,
        "timezone":         "Asia/Jerusalem",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LLBG/date/",
    },
    "Seoul": {
        "icao":             "RKSS",
        "asos_station":     "RKSS",
        "lat":              37.56,
        "lon":             126.79,
        "timezone":         "Asia/Seoul",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/RKSS/date/",
    },
    # ── Additional US cities ──────────────────────────────────────────────────
    "Houston": {
        "icao":             "KHOU",
        "asos_station":     "HOU",
        "lat":              29.98,
        "lon":             -95.34,
        "timezone":         "America/Chicago",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KHOU/date/",
    },
    "Los Angeles": {
        "icao":             "KLAX",
        "asos_station":     "LAX",
        "lat":              33.94,
        "lon":            -118.41,
        "timezone":         "America/Los_Angeles",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KLAX/date/",
    },
    "Denver": {
        "icao":             "KDEN",
        "asos_station":     "DEN",
        "lat":              39.86,
        "lon":            -104.67,
        "timezone":         "America/Denver",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KDEN/date/",
    },
    "Austin": {
        "icao":             "KAUS",
        "asos_station":     "AUS",
        "lat":              30.20,
        "lon":             -97.67,
        "timezone":         "America/Chicago",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KAUS/date/",
    },
    "San Francisco": {
        "icao":             "KSFO",
        "asos_station":     "SFO",
        "lat":              37.62,
        "lon":            -122.38,
        "timezone":         "America/Los_Angeles",
        "uses_fahrenheit":  True,
        "wunderground_url": "https://www.wunderground.com/history/daily/KSFO/date/",
    },
    # ── Asian cities ──────────────────────────────────────────────────────────
    "Tokyo": {
        "icao":             "RJTT",
        "asos_station":     "RJTT",
        "lat":              35.55,
        "lon":             139.78,
        "timezone":         "Asia/Tokyo",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/RJTT/date/",
    },
    "Singapore": {
        "icao":             "WSSS",
        "asos_station":     "WSSS",
        "lat":              1.36,
        "lon":             103.99,
        "timezone":         "Asia/Singapore",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/WSSS/date/",
    },
    "Beijing": {
        "icao":             "ZBAA",
        "asos_station":     "ZBAA",
        "lat":              40.07,
        "lon":             116.60,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZBAA/date/",
    },
    "Shanghai": {
        "icao":             "ZSPD",
        "asos_station":     "ZSPD",
        "lat":              31.15,
        "lon":             121.80,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZSPD/date/",
    },
    "Shenzhen": {
        "icao":             "ZGSZ",
        "asos_station":     "ZGSZ",
        "lat":              22.64,
        "lon":             113.81,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZGSZ/date/",
    },
    "Wuhan": {
        "icao":             "ZHHH",
        "asos_station":     "ZHHH",
        "lat":              30.78,
        "lon":             114.21,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZHHH/date/",
    },
    "Chengdu": {
        "icao":             "ZUUU",
        "asos_station":     "ZUUU",
        "lat":              30.57,
        "lon":             103.95,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZUUU/date/",
    },
    "Chongqing": {
        "icao":             "ZUCK",
        "asos_station":     "ZUCK",
        "lat":              29.72,
        "lon":             106.64,
        "timezone":         "Asia/Shanghai",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/ZUCK/date/",
    },
    "Taipei": {
        "icao":             "RCTP",
        "asos_station":     "RCTP",
        "lat":              25.07,
        "lon":             121.23,
        "timezone":         "Asia/Taipei",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/RCTP/date/",
    },
    "Lucknow": {
        "icao":             "VILK",
        "asos_station":     "VILK",
        "lat":              26.76,
        "lon":              80.89,
        "timezone":         "Asia/Kolkata",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/VILK/date/",
    },
    # ── European cities ───────────────────────────────────────────────────────
    "Ankara": {
        "icao":             "LTAC",
        "asos_station":     "LTAC",
        "lat":              40.13,
        "lon":              32.99,
        "timezone":         "Europe/Istanbul",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LTAC/date/",
    },
    "Warsaw": {
        "icao":             "EPWA",
        "asos_station":     "EPWA",
        "lat":              52.17,
        "lon":              20.97,
        "timezone":         "Europe/Warsaw",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/EPWA/date/",
    },
    "Istanbul": {
        "icao":             "LTFM",
        "asos_station":     "LTFM",
        "lat":              41.26,
        "lon":              28.74,
        "timezone":         "Europe/Istanbul",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/LTFM/date/",
    },
    # ── Other cities ──────────────────────────────────────────────────────────
    "Wellington": {
        "icao":             "NZWN",
        "asos_station":     "NZWN",
        "lat":             -41.33,
        "lon":             174.81,
        "timezone":         "Pacific/Auckland",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/NZWN/date/",
    },
    "Mexico City": {
        "icao":             "MMMX",
        "asos_station":     "MMMX",
        "lat":              19.44,
        "lon":             -99.07,
        "timezone":         "America/Mexico_City",
        "uses_fahrenheit":  False,
        "wunderground_url": "https://www.wunderground.com/history/daily/MMMX/date/",
    },
}

# ── TSA passenger market configuration ───────────────────────────────────────

# Hub airports used for weather impact on TSA counts
# If 2+ of these have bad weather, passenger counts drop ~3% per affected hub
TSA_HUB_AIRPORTS = {
    "KATL": {"lat": 33.64,  "lon":  -84.43, "timezone": "America/New_York"},    # Atlanta
    "KDFW": {"lat": 32.90,  "lon":  -97.04, "timezone": "America/Chicago"},     # Dallas/Fort Worth
    "KORD": {"lat": 41.98,  "lon":  -87.90, "timezone": "America/Chicago"},     # Chicago O'Hare
    "KDEN": {"lat": 39.86,  "lon": -104.67, "timezone": "America/Denver"},      # Denver
    "KLAX": {"lat": 33.94,  "lon": -118.41, "timezone": "America/Los_Angeles"}, # Los Angeles
}
TSA_HUB_BAD_WEATHER_MIN_COUNT = 2   # min hubs with bad wx to trigger flag
TSA_WEATHER_DROP_PER_HUB      = 0.03  # 3% passenger drop per bad-wx hub beyond threshold

# Precipitation (mm/day) or wind speed (km/h) thresholds for "bad weather" at a hub
TSA_BAD_WEATHER_PRECIP_MM  = 5.0
TSA_BAD_WEATHER_WIND_KMH   = 35.0

# Peak-travel holiday periods by year.
# Stored as (MM-DD, MM-DD) so get_holiday_info() can apply them to any year.
# Add new years as they approach; the lookup function uses the current year's entry.
TSA_HOLIDAY_PERIODS = {
    2026: [
        {"name": "New Year",       "start": "01-02", "end": "01-04", "multiplier": 1.18},
        {"name": "Presidents Day", "start": "02-13", "end": "02-17", "multiplier": 1.10},
        {"name": "Spring Break",   "start": "03-14", "end": "03-29", "multiplier": 1.18},
        {"name": "Memorial Day",   "start": "05-22", "end": "05-26", "multiplier": 1.18},
        {"name": "July 4th",       "start": "07-02", "end": "07-06", "multiplier": 1.18},
        {"name": "Labor Day",      "start": "09-04", "end": "09-07", "multiplier": 1.15},
        {"name": "Columbus Day",   "start": "10-09", "end": "10-12", "multiplier": 1.10},
        {"name": "Thanksgiving",   "start": "11-20", "end": "11-25", "multiplier": 1.18},
        {"name": "Christmas",      "start": "12-18", "end": "12-28", "multiplier": 1.18},
    ],
    2027: [
        {"name": "New Year",       "start": "01-01", "end": "01-03", "multiplier": 1.18},
        {"name": "Presidents Day", "start": "02-12", "end": "02-16", "multiplier": 1.10},
        {"name": "Spring Break",   "start": "03-13", "end": "03-28", "multiplier": 1.18},
        {"name": "Memorial Day",   "start": "05-28", "end": "06-01", "multiplier": 1.18},
        {"name": "July 4th",       "start": "07-02", "end": "07-06", "multiplier": 1.18},
        {"name": "Labor Day",      "start": "09-03", "end": "09-06", "multiplier": 1.15},
        {"name": "Columbus Day",   "start": "10-08", "end": "10-11", "multiplier": 1.10},
        {"name": "Thanksgiving",   "start": "11-19", "end": "11-24", "multiplier": 1.18},
        {"name": "Christmas",      "start": "12-17", "end": "12-27", "multiplier": 1.18},
    ],
}

TSA_DATA_URL = "https://www.tsa.gov/travel/passenger-volumes"

# Forecast uncertainty: 5% of forecasted count as 1-sigma
TSA_FORECAST_STD_FRACTION = 0.05

# TSA market bucket boundaries (millions of passengers)
TSA_BUCKETS_M = [None, 2.0, 2.2, 2.4, 2.6, 2.8, None]  # None = open-ended

# Inverted lookup: question keyword → city key
CITY_ALIASES = {
    # US cities
    "new york city": "New York City",
    "nyc":           "New York City",
    "new york":      "New York City",
    "chicago":       "Chicago",
    "atlanta":       "Atlanta",
    "miami":         "Miami",
    "dallas":        "Dallas",
    "seattle":       "Seattle",
    # Europe
    "london":        "London",
    "paris":         "Paris",
    "madrid":        "Madrid",
    "munich":        "Munich",
    "milan":         "Milan",
    # International
    "hong kong":     "Hong Kong",
    "toronto":       "Toronto",
    "buenos aires":  "Buenos Aires",
    "sao paulo":     "Sao Paulo",
    "são paulo":     "Sao Paulo",    # accented variant
    "tel aviv":      "Tel Aviv",
    "tel-aviv":      "Tel Aviv",
    # More US cities
    "houston":       "Houston",
    "los angeles":   "Los Angeles",
    "la":            "Los Angeles",
    "denver":        "Denver",
    "austin":        "Austin",
    "san francisco": "San Francisco",
    "sf":            "San Francisco",
    # Asia
    "seoul":         "Seoul",
    "tokyo":         "Tokyo",
    "singapore":     "Singapore",
    "beijing":       "Beijing",
    "shanghai":      "Shanghai",
    "shenzhen":      "Shenzhen",
    "wuhan":         "Wuhan",
    "chengdu":       "Chengdu",
    "chongqing":     "Chongqing",
    "taipei":        "Taipei",
    "lucknow":       "Lucknow",
    # Europe
    "ankara":        "Ankara",
    "warsaw":        "Warsaw",
    "istanbul":      "Istanbul",
    # Other
    "wellington":    "Wellington",
    "mexico city":   "Mexico City",
}
