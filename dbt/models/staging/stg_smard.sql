-- Deduplicate the append-only raw table: keep the latest ingested value per (series, ts).
-- This makes re-runs and overlapping lookback windows idempotent.
with ranked as (

    select
        series,
        ts,
        value,
        row_number() over (
            partition by series, ts
            order by ingested_at desc
        ) as rn
    from {{ source('raw', 'smard_raw') }}
    where value is not null

)

select
    concat(series, '|', cast(ts as string)) as series_ts_key,
    series,
    ts,
    value
from ranked
where rn = 1
