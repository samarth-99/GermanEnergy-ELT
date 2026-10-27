-- Keep the latest ingested record per (location, ts).
with ranked as (

    select
        location,
        ts,
        temperature_c,
        wind_speed_kmh,
        sunshine_min,
        cloud_cover_pct,
        precipitation_mm,
        row_number() over (
            partition by location, ts
            order by ingested_at desc
        ) as rn
    from {{ source('raw', 'weather_raw') }}

)

select
    concat(location, '|', cast(ts as string)) as location_ts_key,
    location,
    ts,
    temperature_c,
    wind_speed_kmh,
    sunshine_min,
    cloud_cover_pct,
    precipitation_mm
from ranked
where rn = 1
