"""Thin BigQuery helpers. Uses load jobs (not streaming inserts), which also work in the sandbox."""
from __future__ import annotations

import pandas as pd
from google.cloud import bigquery

from . import config

SMARD_SCHEMA = [
    bigquery.SchemaField("series", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ts", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("value", "FLOAT64"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

WEATHER_SCHEMA = [
    bigquery.SchemaField("location", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ts", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("temperature_c", "FLOAT64"),
    bigquery.SchemaField("wind_speed_kmh", "FLOAT64"),
    bigquery.SchemaField("sunshine_min", "FLOAT64"),
    bigquery.SchemaField("cloud_cover_pct", "FLOAT64"),
    bigquery.SchemaField("precipitation_mm", "FLOAT64"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]


def get_client() -> bigquery.Client:
    return bigquery.Client(project=config.require_project(), location=config.BQ_LOCATION)


def ensure_dataset(client: bigquery.Client, dataset: str) -> None:
    ds = bigquery.Dataset(f"{client.project}.{dataset}")
    ds.location = config.BQ_LOCATION
    client.create_dataset(ds, exists_ok=True)


def ensure_table(client: bigquery.Client, dataset: str, table: str, schema) -> None:
    client.create_table(
        bigquery.Table(f"{client.project}.{dataset}.{table}", schema=schema), exists_ok=True
    )


def max_ts_by_key(client: bigquery.Client, dataset: str, table: str, key: str) -> dict:
    """Newest stored timestamp per key (series or location), used for incremental loads."""
    sql = (
        f"SELECT {key} AS k, MAX(ts) AS max_ts "
        f"FROM `{client.project}.{dataset}.{table}` GROUP BY k"
    )
    return {row.k: row.max_ts for row in client.query(sql).result()}


def load_df(
    client: bigquery.Client,
    df: pd.DataFrame,
    dataset: str,
    table: str,
    schema=None,
    truncate: bool = False,
) -> int:
    """Load a DataFrame into BigQuery. Appends by default."""
    if df.empty:
        return 0
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_TRUNCATE
            if truncate
            else bigquery.WriteDisposition.WRITE_APPEND
        ),
    )
    job = client.load_table_from_dataframe(
        df, f"{client.project}.{dataset}.{table}", job_config=job_config
    )
    job.result()
    return len(df)
