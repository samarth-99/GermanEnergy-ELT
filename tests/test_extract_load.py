from datetime import datetime, timedelta, timezone

from ingestion.extract_load import compute_since

DEFAULT = datetime(2023, 1, 1, tzinfo=timezone.utc)


def test_override_wins():
    override = datetime(2024, 5, 1, tzinfo=timezone.utc)
    last = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert compute_since("solar", {"solar": last}, override, DEFAULT) == override


def test_backfill_when_nothing_stored():
    assert compute_since("solar", {}, None, DEFAULT) == DEFAULT


def test_incremental_uses_lookback():
    last = datetime(2025, 6, 10, 12, tzinfo=timezone.utc)
    since = compute_since("solar", {"solar": last}, None, DEFAULT)
    assert since < last
    assert last - since == timedelta(hours=48)
