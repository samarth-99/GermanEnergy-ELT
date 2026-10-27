import pandas as pd

from ingestion.smard import parse_series, select_chunks


def test_select_chunks_returns_all_when_no_start():
    assert select_chunks([100, 200, 300], None) == [100, 200, 300]


def test_select_chunks_includes_chunk_containing_start():
    # since=250 lives inside the chunk that starts at 200
    assert select_chunks([100, 200, 300], 250) == [200, 300]


def test_select_chunks_start_before_first_chunk():
    assert select_chunks([100, 200], 50) == [100, 200]


def test_parse_series_drops_nulls_and_old_rows():
    raw = [[1_700_000_000_000, 10.5], [1_700_003_600_000, None], [1_700_007_200_000, 12.0]]
    df = parse_series("price_day_ahead", raw, since_ms=1_700_000_000_001)
    assert list(df["value"]) == [12.0]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["series"].iloc[0] == "price_day_ahead"


def test_parse_series_empty_input_keeps_columns():
    df = parse_series("solar", [])
    assert list(df.columns) == ["series", "ts", "value"]
    assert df.empty
