"""Day-ahead price forecast: baselines vs. gradient boosting, evaluated on a time-based split.

Reads  marts.mart_hourly_features
Writes marts.price_forecasts   (test-period predictions, replaced each run)
       marts.forecast_metrics  (append-only metrics history, one block per run)
       ml/artifacts/*          (plots, CSVs, results.md)

Models compared on identical test rows
  naive_24h          same hour yesterday
  naive_168h         same hour last week
  naive_standard     literature benchmark: last week for Mon/Sat/Sun, yesterday for Tue-Fri
  model_no_weather   gradient boosting without weather features (weather ablation)
  model              gradient boosting, trained once on everything before the test window
  model_walkforward  same model, retrained at the start of each test month (expanding window)

Leakage rules
  * Split is by time: training data lies strictly before the period it predicts.
  * Features are calendar values, weather, and lags of >= 24h. Same-day actual load,
    wind and solar are NOT used, because they are unknown at bidding time.
  * Weather is observed weather standing in for weather forecasts. The ablation bounds
    how much that matters: with real forecast weather, accuracy would fall between
    model_no_weather and model.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import holidays
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402

log = logging.getLogger("forecast")

TARGET = "price_eur_mwh"
WEATHER_FEATURES = [
    "temperature_c",
    "wind_speed_kmh",
    "sunshine_min",
    "cloud_cover_pct",
    "precipitation_mm",
]
FEATURES = (
    ["hour_of_day", "day_of_week", "month", "is_weekend", "is_holiday"]
    + WEATHER_FEATURES
    + ["price_lag_24h", "price_lag_168h", "residual_load_lag_24h", "load_lag_24h"]
)
FEATURES_NO_WEATHER = [f for f in FEATURES if f not in WEATHER_FEATURES]

# model name -> prediction column. Order is the display order.
MODELS = {
    "naive_24h": "pred_naive_24h",
    "naive_168h": "pred_naive_168h",
    "naive_standard": "pred_naive_standard",
    "model_no_weather": "pred_model_no_weather",
    "model": "pred_model",
    "model_walkforward": "pred_model_walkforward",
}
MART_COLUMNS = ["ts_utc", "season", TARGET] + [f for f in FEATURES if f != "is_holiday"]


# ----------------------------------------------------------------------------- logic
def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add holiday flag, drop rows that cannot be scored fairly, sort by time."""
    df = df.copy()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    local_dates = df["ts_utc"].dt.tz_convert("Europe/Berlin").dt.date
    years = sorted({d.year for d in local_dates})
    de_holidays = holidays.Germany(years=years)
    df["is_holiday"] = [int(d in de_holidays) for d in local_dates]
    df["is_weekend"] = df["is_weekend"].astype(int)
    # Same rows for every model, so the comparison is fair.
    df = df.dropna(subset=[TARGET, "price_lag_24h", "price_lag_168h"])
    return df.sort_values("ts_utc").reset_index(drop=True)


def split_by_time(df: pd.DataFrame, test_start: pd.Timestamp):
    train = df[df["ts_utc"] < test_start]
    test = df[df["ts_utc"] >= test_start]
    if train.empty or test.empty:
        raise ValueError(
            f"Empty split (train={len(train)}, test={len(test)}). Check test_start={test_start} "
            "and that enough history is loaded."
        )
    return train, test


def mae_rmse(y_true, y_pred) -> tuple[float, float]:
    err = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return float(np.mean(np.abs(err))), float(np.sqrt(np.mean(err**2)))


def fit_model(train: pd.DataFrame, features: list[str] = FEATURES) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_iter=400,
        max_depth=6,
        l2_regularization=1.0,
        random_state=42,
    )
    model.fit(train[features], train[TARGET])
    return model


def standard_naive(test: pd.DataFrame) -> np.ndarray:
    """Common benchmark in the electricity price forecasting literature:
    last week's price for Monday, Saturday and Sunday; yesterday's price for Tuesday to Friday.
    (Monday's 'yesterday' is a Sunday, which is why it uses last week instead.)
    day_of_week is Monday = 0, in local time.
    """
    weekly = test["day_of_week"].isin([0, 5, 6]).to_numpy()
    return np.where(weekly, test["price_lag_168h"].to_numpy(), test["price_lag_24h"].to_numpy())


def walk_forward_blocks(test: pd.DataFrame, test_start: pd.Timestamp):
    """Split the test window into blocks, each with the cutoff its model may train up to.

    The first block starts at test_start (so its model equals the single-split model);
    later blocks start at the first day of each following month. A model for a block is
    trained on rows strictly before that block's cutoff, so nothing leaks backwards.
    """
    month_keys = test["ts_utc"].dt.strftime("%Y-%m").unique()
    month_starts = [pd.Timestamp(f"{k}-01", tz="UTC") for k in month_keys]
    cutoffs = [test_start] + [m for m in month_starts if m > test_start]
    blocks = []
    for i, cutoff in enumerate(cutoffs):
        mask = test["ts_utc"] >= cutoff
        if i + 1 < len(cutoffs):
            mask &= test["ts_utc"] < cutoffs[i + 1]
        block = test[mask]
        if not block.empty:
            blocks.append((cutoff, block))
    return blocks


def walk_forward_predict(df: pd.DataFrame, test: pd.DataFrame, test_start: pd.Timestamp) -> np.ndarray:
    """Retrain on an expanding window at the start of each test month."""
    preds = pd.Series(np.nan, index=test.index, dtype="float64")
    blocks = walk_forward_blocks(test, test_start)
    for i, (cutoff, block) in enumerate(blocks, start=1):
        train = df[df["ts_utc"] < cutoff]
        model = fit_model(train)
        preds.loc[block.index] = model.predict(block[FEATURES])
        log.info("walk-forward %d/%d: from %s, %d train rows, %d test rows",
                 i, len(blocks), cutoff.date(), len(train), len(block))
    return preds.to_numpy()


def build_predictions(model, test: pd.DataFrame) -> pd.DataFrame:
    out = test[["ts_utc", "season", "hour_of_day", "month", TARGET]].copy()
    out = out.rename(columns={TARGET: "actual"})
    out["pred_model"] = model.predict(test[FEATURES])
    out["pred_naive_24h"] = test["price_lag_24h"].to_numpy()
    out["pred_naive_168h"] = test["price_lag_168h"].to_numpy()
    out["pred_naive_standard"] = standard_naive(test)
    out["year_month"] = out["ts_utc"].dt.strftime("%Y-%m")
    return out


def compute_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    """Tidy metrics: overall, and broken down by season, hour of day and month."""
    segments = {
        "overall": None,
        "season": "season",
        "hour_of_day": "hour_of_day",
        "month": "year_month",
    }
    rows = []
    for seg_type, col in segments.items():
        groups = [("all", preds)] if col is None else preds.groupby(col)
        for seg_value, g in groups:
            for model_name, pred_col in MODELS.items():
                if pred_col not in preds.columns:
                    continue
                mae, rmse = mae_rmse(g["actual"], g[pred_col])
                rows.append(
                    {
                        "model": model_name,
                        "segment_type": seg_type,
                        "segment": str(seg_value),
                        "mae": mae,
                        "rmse": rmse,
                        "n": int(len(g)),
                    }
                )
    return pd.DataFrame(rows)


def feature_importance(model, test: pd.DataFrame, sample: int = 3000) -> pd.DataFrame:
    s = test.sample(min(sample, len(test)), random_state=42)
    result = permutation_importance(
        model, s[FEATURES], s[TARGET],
        scoring="neg_mean_absolute_error", n_repeats=3, random_state=42,
    )
    return (
        pd.DataFrame({"feature": FEATURES, "mae_increase": result.importances_mean})
        .sort_values("mae_increase", ascending=False)
        .reset_index(drop=True)
    )


def evaluate(df: pd.DataFrame, test_start: pd.Timestamp, walk_forward: bool = True):
    """Full offline pipeline: returns (predictions, metrics, importance, model)."""
    df = prepare(df)
    train, test = split_by_time(df, test_start)
    log.info("train rows=%d (to %s)  test rows=%d (from %s)",
             len(train), train["ts_utc"].max(), len(test), test["ts_utc"].min())

    model = fit_model(train)
    preds = build_predictions(model, test)

    model_nw = fit_model(train, FEATURES_NO_WEATHER)
    preds["pred_model_no_weather"] = model_nw.predict(test[FEATURES_NO_WEATHER])

    if walk_forward:
        preds["pred_model_walkforward"] = walk_forward_predict(df, test, test_start)

    metrics = compute_metrics(preds)
    importance = feature_importance(model, test)
    return preds, metrics, importance, model


# ---------------------------------------------------------------------------- output
def write_artifacts(preds, metrics, importance, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out_dir / "metrics.csv", index=False)
    importance.to_csv(out_dir / "feature_importance.csv", index=False)

    order = [m for m in MODELS if m in set(metrics["model"])]
    overall = (
        metrics[metrics.segment_type == "overall"].set_index("model").loc[order, ["mae", "rmse", "n"]]
    )
    naive_models = [m for m in overall.index if m.startswith("naive")]
    ref_mae = overall.loc[overall.loc[naive_models, "mae"].idxmin(), "mae"]
    overall["mae_gain_vs_best_naive_pct"] = (1 - overall["mae"] / ref_mae) * 100
    season = (
        metrics[metrics.segment_type == "season"]
        .pivot(index="segment", columns="model", values="mae")
        .reindex(["winter", "spring", "summer", "autumn"])
        .reindex(columns=order)
    )

    with open(out_dir / "results.md", "w") as fh:
        fh.write("## Overall test-period error (EUR/MWh)\n\n")
        fh.write(overall.round(2).to_markdown() + "\n\n")
        fh.write("## MAE by season (EUR/MWh)\n\n")
        fh.write(season.round(2).to_markdown() + "\n\n")
        if "model_no_weather" in overall.index:
            gain = (1 - overall.loc["model", "mae"] / overall.loc["model_no_weather", "mae"]) * 100
            fh.write("## Weather ablation\n\n")
            fh.write(
                f"Adding observed weather lowers MAE by {gain:.1f}% "
                f"({overall.loc['model_no_weather', 'mae']:.2f} -> {overall.loc['model', 'mae']:.2f}). "
                "Because observed weather is not available at bidding time, accuracy with real "
                "weather forecasts would lie between these two models.\n\n"
            )
        fh.write("## Top features (permutation importance, MAE increase)\n\n")
        fh.write(importance.head(8).round(3).to_markdown(index=False) + "\n")

    plot_cols = [c for c in ["naive_standard", "model_no_weather", "model", "model_walkforward"] if c in season]
    fig, ax = plt.subplots(figsize=(9, 4))
    season[plot_cols].plot(kind="bar", ax=ax)
    ax.set_ylabel("MAE (EUR/MWh)")
    ax.set_xlabel("")
    ax.set_title("Forecast error by season (lower is better)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "mae_by_season.png", dpi=150)
    plt.close(fig)

    last_week = preds[preds["ts_utc"] >= preds["ts_utc"].max() - pd.Timedelta(days=7)]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(last_week["ts_utc"], last_week["actual"], label="actual", linewidth=2)
    best_col = "pred_model_walkforward" if "pred_model_walkforward" in last_week else "pred_model"
    ax.plot(last_week["ts_utc"], last_week[best_col], label=best_col.replace("pred_", ""))
    ax.plot(last_week["ts_utc"], last_week["pred_naive_standard"], label="naive standard", alpha=0.6)
    ax.set_ylabel("EUR/MWh")
    ax.set_title("Most recent week in the test period")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_dir / "recent_week.png", dpi=150)
    plt.close(fig)


def write_to_bigquery(preds: pd.DataFrame, metrics: pd.DataFrame) -> None:
    from ingestion import bq  # imported here so offline tests do not need GCP

    client = bq.get_client()
    bq.ensure_dataset(client, "marts")
    run_ts = pd.Timestamp(datetime.now(timezone.utc))
    out_preds = preds.assign(run_ts=run_ts)
    out_metrics = metrics.assign(run_ts=run_ts)
    bq.load_df(client, out_preds, "marts", "price_forecasts", truncate=True)
    bq.load_df(client, out_metrics, "marts", "forecast_metrics", truncate=False)
    log.info("wrote %d predictions and %d metric rows to BigQuery", len(out_preds), len(out_metrics))


def load_mart() -> pd.DataFrame:
    from ingestion import bq

    client = bq.get_client()
    cols = ", ".join(MART_COLUMNS)
    sql = f"SELECT {cols} FROM `{client.project}.marts.mart_hourly_features` ORDER BY ts_utc"
    return client.query(sql).to_dataframe()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--test-months", type=int, default=12, help="Length of the test window (default 12).")
    parser.add_argument("--artifacts-dir", default="ml/artifacts")
    parser.add_argument("--no-walk-forward", action="store_true", help="Skip monthly retraining (faster).")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate and write local artifacts, skip BigQuery writes.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    df = load_mart()
    log.info("loaded %d rows from the mart", len(df))
    latest = pd.to_datetime(df["ts_utc"], utc=True).max()
    test_start = latest.normalize() - pd.DateOffset(months=args.test_months)

    preds, metrics, importance, _ = evaluate(df, test_start, walk_forward=not args.no_walk_forward)
    write_artifacts(preds, metrics, importance, Path(args.artifacts_dir))
    print((Path(args.artifacts_dir) / "results.md").read_text())

    if not args.dry_run:
        write_to_bigquery(preds, metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
