from datetime import date, datetime, timezone

import pandas as pd

from ingestion import config, extract_load, smard, weather


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSmardSession:
    """Serves an index of 3 weekly chunks, each with 2 hourly values."""

    def get(self, url, timeout=None, params=None):
        if url.endswith("index_hour.json"):
            return FakeResponse({"timestamps": [3_600_000, 7_200_000_000, 14_400_000_000]})
        ts = int(url.rsplit("_", 1)[1].split(".")[0])
        return FakeResponse({"series": [[ts, 1.0], [ts + 3_600_000, 2.0]]})


class FakeWeatherSession:
    def get(self, url, timeout=None, params=None):
        day = params["date"]
        return FakeResponse({"weather": [
            {"timestamp": f"{day}T00:00:00+00:00", "temperature": 10.0, "wind_speed": 5.0,
             "sunshine": 0.0, "cloud_cover": 50, "precipitation": 0.0}
        ]})


def test_smard_parallel_fetch_keeps_chunk_order(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_PAUSE_S", 0)
    df = smard.fetch_series(FakeSmardSession(), "solar", since=None)
    assert len(df) == 6
    assert df["ts"].is_monotonic_increasing
    assert set(df["series"]) == {"solar"}


def test_date_windows_cover_range_without_gaps():
    windows = weather.date_windows(date(2025, 1, 1), date(2025, 1, 20), 7)
    assert windows[0][0] == date(2025, 1, 1)
    assert windows[-1][1] == date(2025, 1, 20)
    for (_, end), (nxt, _) in zip(windows, windows[1:]):
        assert (nxt - end).days == 1


def test_weather_parallel_fetch(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_PAUSE_S", 0)
    now = datetime(2025, 1, 20, 12, tzinfo=timezone.utc)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    df = weather.fetch_location(FakeWeatherSession(), "hamburg", 53.5, 10.0, start, now)
    assert len(df) == 3  # three 7-day windows
    assert set(df["location"]) == {"hamburg"}


def test_export_csv_is_bigquery_loadable(tmp_path):
    df = pd.DataFrame({
        "series": ["solar"],
        "ts": pd.to_datetime(["2025-01-01T00:00:00Z"]),
        "value": [1.5],
        "ingested_at": pd.to_datetime(["2025-01-02T05:00:00Z"]),
    })
    extract_load.export_csv(df, tmp_path, "smard_raw.csv")
    lines = (tmp_path / "smard_raw.csv").read_text().splitlines()
    assert lines[0] == "series,ts,value,ingested_at"
    assert lines[1].startswith("solar,2025-01-01 00:00:00+00:00,1.5,")
