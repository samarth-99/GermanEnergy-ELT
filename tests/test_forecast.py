import numpy as np
import pandas as pd

from ml.forecast import FEATURES, MODELS, TARGET, evaluate


def synthetic_mart(days: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=days * 24, freq="h", tz="UTC")
    local = idx.tz_convert("Europe/Berlin")
    hour = local.hour.to_numpy()
    dow = local.dayofweek.to_numpy()
    month = local.month.to_numpy()
    wind = rng.gamma(2.0, 8.0, len(idx))
    price = 60 + 25 * np.sin((hour - 6) / 24 * 2 * np.pi) - 0.8 * wind + 10 * np.isin(month, [12, 1, 2]) \
        - 8 * (dow >= 5) + rng.normal(0, 5, len(idx))
    df = pd.DataFrame({
        "ts_utc": idx,
        "season": pd.Series(month).map(
            lambda m: "winter" if m in (12, 1, 2) else "spring" if m in (3, 4, 5)
            else "summer" if m in (6, 7, 8) else "autumn").to_numpy(),
        TARGET: price,
        "hour_of_day": hour, "day_of_week": dow, "month": month,
        "is_weekend": dow >= 5,
        "temperature_c": rng.normal(10, 8, len(idx)),
        "wind_speed_kmh": wind,
        "sunshine_min": rng.uniform(0, 60, len(idx)),
        "cloud_cover_pct": rng.uniform(0, 100, len(idx)),
        "precipitation_mm": rng.exponential(0.2, len(idx)),
    })
    df["price_lag_24h"] = df[TARGET].shift(24)
    df["price_lag_168h"] = df[TARGET].shift(168)
    df["residual_load_lag_24h"] = rng.normal(40000, 5000, len(idx))
    df["load_lag_24h"] = rng.normal(55000, 5000, len(idx))
    return df


def test_evaluate_runs_and_has_no_time_leakage():
    df = synthetic_mart()
    test_start = pd.Timestamp("2025-03-01", tz="UTC")
    preds, metrics, importance, model = evaluate(df, test_start)

    assert preds["ts_utc"].min() >= test_start
    assert set(metrics["model"]) == set(MODELS)
    assert set(metrics["segment_type"]) == {"overall", "season", "hour_of_day", "month"}
    assert set(importance["feature"]) == set(FEATURES)
    assert np.isfinite(metrics["mae"]).all()


def test_model_beats_weekly_naive_on_structured_data():
    df = synthetic_mart()
    _, metrics, _, _ = evaluate(df, pd.Timestamp("2025-03-01", tz="UTC"))
    overall = metrics[metrics.segment_type == "overall"].set_index("model")["mae"]
    assert overall["model"] < overall["naive_168h"]
