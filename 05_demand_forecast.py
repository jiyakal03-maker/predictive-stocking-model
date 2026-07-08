"""
demand_forecast.py
------------------
Forecasts future demand per part using three methods depending on part behavior:

    - Stable parts:          Moving Average
    - Moderate parts:        Exponential Smoothing
    - Seasonal parts:        Holt-Winters (triple exponential smoothing)
    - Highly variable parts: Moving Average (simple wins on noisy data)

Inputs:
    - Cleaned PO history DataFrame with [PartNum, OrderDate, RelQty]

Output:
    - Full forecast DataFrame with forecasted demand per part per month
    - Summary DataFrame with method used per part + average forecasted demand
"""

import pandas as pd
import numpy as np
import warnings
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")

CV_HIGH_VARIABILITY = 1.0
CV_STABLE = 0.3
DEFAULT_LEAD_TIME_DAYS = 30


def aggregate_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["OrderDate"] = pd.to_datetime(df["OrderDate"])
    df["Month"] = df["OrderDate"].dt.to_period("M")
    monthly = (
        df.groupby(["PartNum", "Month"])["RelQty"]
        .sum()
        .reset_index()
        .rename(columns={"RelQty": "demand"})
    )
    monthly["Month"] = monthly["Month"].dt.to_timestamp()
    return monthly


def classify_part(series: pd.Series) -> str:
    if series.std() == 0 or series.mean() == 0:
        return "stable"
    cv = series.std() / series.mean()
    if cv >= CV_HIGH_VARIABILITY:
        return "highly_variable"
    if len(series) >= 24:
        try:
            from statsmodels.tsa.seasonal import seasonal_decompose
            decomp = seasonal_decompose(series, model="additive", period=12, extrapolate_trend="freq")
            seasonal_strength = decomp.seasonal.std() / (decomp.seasonal.std() + decomp.resid.std())
            if seasonal_strength > 0.3:
                return "seasonal"
        except Exception:
            pass
    if cv < CV_STABLE:
        return "stable"
    return "moderate"


def forecast_moving_average(series: pd.Series, periods: int = 3, horizon: int = 3) -> pd.Series:
    window = min(periods, len(series))
    avg = series.iloc[-window:].mean()
    idx = pd.date_range(series.index[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    return pd.Series([avg] * horizon, index=idx)


def forecast_exponential_smoothing(series: pd.Series, horizon: int = 3) -> pd.Series:
    try:
        model = ExponentialSmoothing(series, trend=None, seasonal=None)
        fit = model.fit(optimized=True)
        return fit.forecast(horizon)
    except Exception:
        return forecast_moving_average(series, horizon=horizon)


def forecast_holt_winters(series: pd.Series, horizon: int = 3) -> pd.Series:
    if len(series) < 24:
        return forecast_exponential_smoothing(series, horizon=horizon)
    try:
        model = ExponentialSmoothing(
            series,
            trend="add",
            seasonal="add",
            seasonal_periods=12,
        )
        fit = model.fit(optimized=True)
        return fit.forecast(horizon)
    except Exception:
        return forecast_exponential_smoothing(series, horizon=horizon)


def run_forecasts(df: pd.DataFrame, horizon: int = 3, ma_window: int = 3) -> pd.DataFrame:
    monthly = aggregate_to_monthly(df)
    results = []

    for part, group in monthly.groupby("PartNum"):
        series = group.set_index("Month")["demand"].sort_index()
        series.index = pd.DatetimeIndex(series.index)
        series = series.asfreq("MS", fill_value=0)

        if len(series) < 3:
            part_type = "insufficient_history"
            avg = series.mean() if len(series) > 0 else 0
            idx = pd.date_range(series.index[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
            forecast = pd.Series([avg] * horizon, index=idx)
            method = "average_fallback"
        else:
            part_type = classify_part(series)
            if part_type == "seasonal":
                forecast = forecast_holt_winters(series, horizon=horizon)
                method = "holt_winters"
            elif part_type == "stable":
                forecast = forecast_moving_average(series, periods=ma_window, horizon=horizon)
                method = f"moving_average_{ma_window}m"
            else:
                forecast = forecast_exponential_smoothing(series, horizon=horizon)
                method = "exponential_smoothing"

        for month, value in forecast.items():
            results.append({
                "PartNum": part,
                "forecast_month": month,
                "forecasted_demand": max(0, round(value, 2)),
                "method": method,
                "part_type": part_type,
            })

    return pd.DataFrame(results)


def forecast_summary(df: pd.DataFrame, horizon: int = 3) -> pd.DataFrame:
    forecasts = run_forecasts(df, horizon=horizon)
    summary = (
        forecasts.groupby(["PartNum", "method", "part_type"])["forecasted_demand"]
        .mean()
        .round(2)
        .reset_index()
        .rename(columns={"forecasted_demand": "avg_forecasted_monthly_demand"})
    )
    return summary


if __name__ == "__main__":
    data = pd.read_csv("spend_clean.csv")

    print("=== Full Forecast (next 3 months) ===")
    print(run_forecasts(data, horizon=3).head(10).to_string(index=False))

    print("\n=== Summary (avg monthly demand per part) ===")
    summary = forecast_summary(data)
    print(summary.head(10).to_string(index=False))
    summary.to_csv("forecast_output.csv", index=False)
    print(f"\nSaved forecast_output.csv  ({len(summary)} rows)")