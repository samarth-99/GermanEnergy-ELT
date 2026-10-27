"""Extract hourly time series from the SMARD chart_data API.

URL scheme (note that filter and region appear twice, which is how the API works):
  index:  {BASE}/{filter}/{region}/index_{resolution}.json
  series: {BASE}/{filter}/{region}/{filter}_{region}_{resolution}_{timestamp}.json
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd

from . import config

log = logging.getLogger(__name__)

EMPTY_COLUMNS = ["series", "ts", "value"]


def get_index(session, filter_id: int, region: str, resolution: str) -> list[int]:
    url = f"{config.SMARD_BASE_URL}/{filter_id}/{region}/index_{resolution}.json"
    resp = session.get(url, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return sorted(int(t) for t in resp.json()["timestamps"])


def get_chunk(session, filter_id: int, region: str, resolution: str, ts_ms: int) -> list:
    url = (
        f"{config.SMARD_BASE_URL}/{filter_id}/{region}/"
        f"{filter_id}_{region}_{resolution}_{ts_ms}.json"
    )
    resp = session.get(url, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("series", [])


def select_chunks(timestamps: list[int], since_ms: int | None) -> list[int]:
    """Pick the chunk files that can contain data at or after `since_ms`.

    A chunk file is named by its first timestamp, so we need the last chunk that
    starts at or before `since_ms`, plus every chunk after it.
    """
    if since_ms is None:
        return list(timestamps)
    earlier = [t for t in timestamps if t <= since_ms]
    start = max(earlier) if earlier else None
    return [t for t in timestamps if start is None or t >= start]


def parse_series(name: str, raw_series: list, since_ms: int | None = None) -> pd.DataFrame:
    """Convert [[ts_ms, value], ...] into a tidy frame. Null values (future hours) are dropped."""
    rows = [
        (int(ts), float(value))
        for ts, value in raw_series
        if value is not None and (since_ms is None or int(ts) >= since_ms)
    ]
    df = pd.DataFrame(rows, columns=["ts_ms", "value"]).astype(
        {"ts_ms": "int64", "value": "float64"}
    )
    return pd.DataFrame(
        {
            "series": name,
            "ts": pd.to_datetime(df["ts_ms"], unit="ms", utc=True),
            "value": df["value"],
        }
    )


def fetch_series(session, name: str, since: datetime | None) -> pd.DataFrame:
    spec = config.SMARD_SERIES[name]
    resolution = config.SMARD_RESOLUTION
    timestamps = get_index(session, spec["filter"], spec["region"], resolution)
    since_ms = int(since.timestamp() * 1000) if since else None
    chunks = select_chunks(timestamps, since_ms)
    log.info("smard %s: %d chunk files to fetch (since=%s)", name, len(chunks), since)

    def fetch_one(ts_ms: int) -> pd.DataFrame:
        raw = get_chunk(session, spec["filter"], spec["region"], resolution, ts_ms)
        time.sleep(config.REQUEST_PAUSE_S)
        return parse_series(name, raw, since_ms)

    with ThreadPoolExecutor(max_workers=config.SMARD_WORKERS) as pool:
        frames = list(pool.map(fetch_one, chunks))  # map keeps chunk order
    if not frames:
        return pd.DataFrame(columns=EMPTY_COLUMNS)
    return pd.concat(frames, ignore_index=True)
