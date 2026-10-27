{{ config(severity='warn') }}
-- Warns if any hour between 30 and 3 days ago is missing from the mart.
with expected as (

    select ts
    from unnest(generate_timestamp_array(
        timestamp_sub(timestamp_trunc(current_timestamp(), hour), interval 30 day),
        timestamp_sub(timestamp_trunc(current_timestamp(), hour), interval 3 day),
        interval 1 hour
    )) as ts

)

select e.ts as missing_hour
from expected as e
left join {{ ref('mart_hourly_features') }} as m
    on m.ts_utc = e.ts
where m.ts_utc is null
