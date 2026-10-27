from datetime import datetime, timezone

from ingestion.weather import parse_weather

NOW = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)


def test_forecast_rows_are_dropped():
    payload = {
        "weather": [
            {"timestamp": "2025-06-01T10:00:00+00:00", "temperature": 18.2, "wind_speed": 12.0,
             "sunshine": 40.0, "cloud_cover": 30, "precipitation": 0.0},
            {"timestamp": "2025-06-01T15:00:00+00:00", "temperature": 21.0},
        ]
    }
    df = parse_weather("hamburg", payload, NOW)
    assert len(df) == 1
    assert df["temperature_c"].iloc[0] == 18.2


def test_missing_fields_become_nan():
    payload = {"weather": [{"timestamp": "2025-06-01T09:00:00+00:00", "temperature": 15.0}]}
    df = parse_weather("munich", payload, NOW)
    assert df["wind_speed_kmh"].isna().all()
