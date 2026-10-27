"""Central configuration. Everything environment-specific comes from env vars."""
import os

GCP_PROJECT = os.environ.get("GCP_PROJECT", "de-energy-pipeline")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "EU")
RAW_DATASET = os.environ.get("RAW_DATASET", "raw")

# First load (or a series with no data yet) starts here. Keep at least ~2 years:
# the forecast uses a 12-month test window and needs history before it to train on.
# Starting after 2022 also avoids the energy-crisis regime.
DEFAULT_START = os.environ.get("DEFAULT_START", "2024-01-01")
# Each daily run re-fetches this many hours before the newest stored timestamp,
# so revised values get picked up. Duplicates are removed in dbt staging.
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "48"))

HTTP_TIMEOUT = 60
REQUEST_PAUSE_S = 0.1
# Parallel requests. Keep these modest: both APIs are free public services.
SMARD_WORKERS = int(os.environ.get("SMARD_WORKERS", "6"))
WEATHER_WORKERS = int(os.environ.get("WEATHER_WORKERS", "3"))
USER_AGENT = "energy-elt-portfolio/0.1"

# --- SMARD (Bundesnetzagentur) -------------------------------------------------
SMARD_BASE_URL = "https://www.smard.de/app/chart_data"
SMARD_RESOLUTION = "hour"
# TODO(first run): verify these filter IDs against SMARD's published filter list.
SMARD_SERIES = {
    "price_day_ahead": {"filter": 4169, "region": "DE-LU"},
    "grid_load": {"filter": 410, "region": "DE"},
    "wind_onshore": {"filter": 4067, "region": "DE"},
    "wind_offshore": {"filter": 1225, "region": "DE"},
    "solar": {"filter": 4068, "region": "DE"},
}

# --- Weather (Bright Sky, a JSON wrapper around DWD open data) ------------------
WEATHER_BASE_URL = "https://api.brightsky.dev/weather"
WEATHER_LOCATIONS = {
    "hamburg": (53.55, 10.00),
    "frankfurt": (50.11, 8.68),
    "munich": (48.14, 11.58),
}
WEATHER_CHUNK_DAYS = 7


def require_project() -> str:
    if not GCP_PROJECT:
        raise RuntimeError("Set the GCP_PROJECT environment variable.")
    return GCP_PROJECT
