"""Extract hourly weather from Bright Sky (https://brightsky.dev), which serves DWD data."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd

from . import config

log = logging.getLogger(__name__)

COLUMNS = [
    "location",
    "ts",
    "temperature_c",
    "wind_speed_kmh",
    "sunshine_min",
    "cloud_cover_pct",
    "precipitation_mm",
]


def parse_weather(location: str, payload: dict, now: datetime) -> pd.DataFrame:
    """Parse one API response. Rows after `now` are forecasts, so they are dropped."""
    rows = []
    for rec in payload.get("weather", []):
        ts = pd.Timestamp(rec["timestamp"]).tz_convert("UTC")
        if ts > now:
            continue
        rows.append(
            {
                "location": location,
                "ts": ts,
                "temperature_c": rec.get("temperature"),
                "wind_speed_kmh": rec.get("wind_speed"),
                "sunshine_min": rec.get("sunshine"),
                "cloud_cover_pct": rec.get("cloud_cover"),
                "precipitation_mm": rec.get("precipitation"),
            }
        )
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in COLUMNS[2:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def date_windows(start: date, last: date, chunk_days: int) -> list[tuple[date, date]]:
    """Split [start, last] into consecutive windows of at most `chunk_days` days."""
    windows = []
    cur = start
    while cur <= last:
        end = min(cur + timedelta(days=chunk_days - 1), last)
        windows.append((cur, end))
        cur = end + timedelta(days=1)
    return windows


def fetch_location(
    session, name: str, lat: float, lon: float, start: datetime, now: datetime
) -> pd.DataFrame:
    windows = date_windows(start.date(), now.date(), config.WEATHER_CHUNK_DAYS)

    def fetch_window(window: tuple[date, date]) -> pd.DataFrame:
        first, end = window
        params = {
            "lat": lat,
            "lon": lon,
            "date": first.isoformat(),
            # ask for the following midnight so the last hour of `end` is included
            "last_date": (end + timedelta(days=1)).isoformat(),
            "tz": "UTC",
        }
        resp = session.get(config.WEATHER_BASE_URL, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        time.sleep(config.REQUEST_PAUSE_S)
        return parse_weather(name, resp.json(), now)

    with ThreadPoolExecutor(max_workers=config.WEATHER_WORKERS) as pool:
        frames = list(pool.map(fetch_window, windows))
    log.info("weather %s: %d requests since %s", name, len(frames), start.date())
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(frames, ignore_index=True)
