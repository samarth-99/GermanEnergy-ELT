-- Simple national proxy: average the three locations per hour.
select
    timestamp_trunc(ts, hour) as ts_utc,
    avg(temperature_c) as temperature_c,
    avg(wind_speed_kmh) as wind_speed_kmh,
    avg(sunshine_min) as sunshine_min,
    avg(cloud_cover_pct) as cloud_cover_pct,
    avg(precipitation_mm) as precipitation_mm
from {{ ref('stg_weather') }}
group by 1
