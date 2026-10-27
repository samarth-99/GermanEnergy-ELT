-- Pivot the long SMARD table to one row per hour.
-- Price is averaged; load and generation are energy values, so they are summed.
select
    timestamp_trunc(ts, hour) as ts_utc,
    avg(if(series = 'price_day_ahead', value, null)) as price_eur_mwh,
    sum(if(series = 'grid_load', value, null)) as load_mwh,
    sum(if(series = 'wind_onshore', value, null)) as wind_onshore_mwh,
    sum(if(series = 'wind_offshore', value, null)) as wind_offshore_mwh,
    sum(if(series = 'solar', value, null)) as solar_mwh
from {{ ref('stg_smard') }}
group by 1
