"""Extract from SMARD and Bright Sky, load the raw data into BigQuery (the "EL" of ELT).

Examples
  python -m ingestion.extract_load --source all --dry-run      # test the APIs, no GCP needed
  python -m ingestion.extract_load --source all                # incremental load
  python -m ingestion.extract_load --source smard --start 2024-01-01   # re-fetch from a date
  python -m ingestion.extract_load --source all --dry-run --export-dir out   # CSVs for manual upload
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import bq, config, smard, weather
from .http import make_session

log = logging.getLogger("extract_load")


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def compute_since(key, max_ts: dict, start_override: datetime | None, default_start: datetime):
    """Where to start fetching for one series/location.

    - explicit --start wins
    - nothing stored yet -> default start (backfill)
    - otherwise newest stored timestamp minus a lookback window (picks up revisions)
    """
    if start_override is not None:
        return start_override
    last = max_ts.get(key)
    if last is None:
        return default_start
    return last - timedelta(hours=config.LOOKBACK_HOURS)


def summarize(df: pd.DataFrame, key: str) -> str:
    if df.empty:
        return "  (no rows)"
    grp = df.groupby(key)["ts"].agg(["count", "min", "max"])
    return grp.to_string()


def export_csv(df: pd.DataFrame, export_dir, filename: str) -> None:
    if export_dir is None or df.empty:
        return
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / filename
    df.to_csv(path, index=False)
    log.info("wrote %s (%d rows)", path, len(df))


def run_smard(client, session, start_override, now, dry_run, export_dir=None) -> int:
    default_start = parse_date(config.DEFAULT_START)
    max_ts = {} if (dry_run or start_override) else bq.max_ts_by_key(
        client, config.RAW_DATASET, "smard_raw", "series"
    )
    frames = []
    for name in config.SMARD_SERIES:
        since = compute_since(name, max_ts, start_override, default_start)
        df = smard.fetch_series(session, name, since)
        if df.empty:
            log.warning("smard %s: no rows returned", name)
        frames.append(df)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    log.info("smard: %d rows\n%s", len(data), summarize(data, "series"))
    if data.empty:
        return 0
    data["ingested_at"] = pd.Timestamp(now)
    export_csv(data, export_dir, "smard_raw.csv")
    if dry_run:
        return len(data)
    return bq.load_df(client, data, config.RAW_DATASET, "smard_raw", bq.SMARD_SCHEMA)


def run_weather(client, session, start_override, now, dry_run, export_dir=None) -> int:
    default_start = parse_date(config.DEFAULT_START)
    max_ts = {} if (dry_run or start_override) else bq.max_ts_by_key(
        client, config.RAW_DATASET, "weather_raw", "location"
    )
    frames = []
    for name, (lat, lon) in config.WEATHER_LOCATIONS.items():
        since = compute_since(name, max_ts, start_override, default_start)
        frames.append(weather.fetch_location(session, name, lat, lon, since, now))
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    log.info("weather: %d rows\n%s", len(data), summarize(data, "location"))
    if data.empty:
        return 0
    data["ingested_at"] = pd.Timestamp(now)
    export_csv(data, export_dir, "weather_raw.csv")
    if dry_run:
        return len(data)
    return bq.load_df(client, data, config.RAW_DATASET, "weather_raw", bq.WEATHER_SCHEMA)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--source", choices=["smard", "weather", "all"], default="all")
    parser.add_argument("--start", help="YYYY-MM-DD. Re-fetch from this date (overrides incremental logic).")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize, but touch no BigQuery.")
    parser.add_argument("--export-dir", type=Path, help="Also write smard_raw.csv / weather_raw.csv here (for manual upload).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    now = datetime.now(timezone.utc)
    start_override = parse_date(args.start) if args.start else None
    session = make_session()

    client = None
    if not args.dry_run:
        client = bq.get_client()
        bq.ensure_dataset(client, config.RAW_DATASET)
        bq.ensure_table(client, config.RAW_DATASET, "smard_raw", bq.SMARD_SCHEMA)
        bq.ensure_table(client, config.RAW_DATASET, "weather_raw", bq.WEATHER_SCHEMA)

    loaded = {}
    if args.source in ("smard", "all"):
        loaded["smard"] = run_smard(client, session, start_override, now, args.dry_run, args.export_dir)
    if args.source in ("weather", "all"):
        loaded["weather"] = run_weather(client, session, start_override, now, args.dry_run, args.export_dir)

    log.info("done%s: %s", " (dry run, nothing written)" if args.dry_run else "", loaded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
