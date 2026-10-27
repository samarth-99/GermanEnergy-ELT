-- One row per hour: market data, weather, calendar features and lagged values.
-- Lags are built with self-joins on the timestamp (not LAG()), so gaps in the
-- data cannot silently shift a lag onto the wrong hour.
with smard as (

    select * from {{ ref('int_smard_hourly') }}

),

weather as (

    select * from {{ ref('int_weather_hourly') }}

),

joined as (

    select
        s.ts_utc,
        datetime(s.ts_utc, 'Europe/Berlin') as ts_local,
        s.price_eur_mwh,
        s.load_mwh,
        s.wind_onshore_mwh,
        s.wind_offshore_mwh,
        s.solar_mwh,
        s.load_mwh - coalesce(s.wind_onshore_mwh, 0) - coalesce(s.wind_offshore_mwh, 0) - coalesce(s.solar_mwh, 0)
            as residual_load_mwh,
        w.temperature_c,
        w.wind_speed_kmh,
        w.sunshine_min,
        w.cloud_cover_pct,
        w.precipitation_mm
    from smard as s
    left join weather as w
        on s.ts_utc = w.ts_utc

),

calendar as (

    select
        *,
        extract(hour from ts_local) as hour_of_day,
        -- Monday = 0 ... Sunday = 6
        mod(extract(dayofweek from ts_local) + 5, 7) as day_of_week,
        extract(month from ts_local) as month,
        extract(year from ts_local) as year,
        case
            when extract(month from ts_local) in (12, 1, 2) then 'winter'
            when extract(month from ts_local) in (3, 4, 5) then 'spring'
            when extract(month from ts_local) in (6, 7, 8) then 'summer'
            else 'autumn'
        end as season
    from joined

)

select
    c.ts_utc,
    c.ts_local,
    c.year,
    c.month,
    c.season,
    c.day_of_week,
    c.day_of_week >= 5 as is_weekend,
    c.hour_of_day,

    c.price_eur_mwh,
    c.load_mwh,
    c.wind_onshore_mwh,
    c.wind_offshore_mwh,
    c.solar_mwh,
    c.residual_load_mwh,

    c.temperature_c,
    c.wind_speed_kmh,
    c.sunshine_min,
    c.cloud_cover_pct,
    c.precipitation_mm,

    -- known at bidding time: yesterday's and last week's outcomes
    l24.price_eur_mwh as price_lag_24h,
    l168.price_eur_mwh as price_lag_168h,
    l24.residual_load_mwh as residual_load_lag_24h,
    l24.load_mwh as load_lag_24h
from calendar as c
left join calendar as l24
    on l24.ts_utc = timestamp_sub(c.ts_utc, interval 24 hour)
left join calendar as l168
    on l168.ts_utc = timestamp_sub(c.ts_utc, interval 168 hour)
