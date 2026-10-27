-- Returns offending rows (dbt treats any returned row as a failure).
-- Bounds are deliberately generous; they catch unit errors, not market spikes.
select ts_utc, price_eur_mwh
from {{ ref('mart_hourly_features') }}
where price_eur_mwh < -1000
   or price_eur_mwh > 5000
