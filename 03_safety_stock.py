"""
03_safety_stock.py
------------------
Computes safety stock for a single part.

Formula:
    Safety Stock = Z * StdDailyDemand * sqrt(LeadTimeDays)

Input (part_data — dict or pd.Series):
    StdDailyDemand : float  standard deviation of daily demand
    LeadTimeDays   : float  replenishment lead time in calendar days

Output:
    float — safety stock quantity, rounded to 1 decimal place
"""

import math
import pandas as pd

_Z_SCORES = {
    0.90: 1.28,
    0.95: 1.65,
    0.98: 2.05,
    0.99: 2.33,
}


def compute_safety_stock(part_data, service_level=0.95):
    """Return safety stock for one part given demand std dev and lead time."""
    Z = _Z_SCORES.get(service_level)
    if Z is None:
        raise ValueError(
            f"service_level must be one of {list(_Z_SCORES.keys())}. Got {service_level}."
        )
    ss = Z * part_data["StdDailyDemand"] * math.sqrt(part_data["LeadTimeDays"])
    return round(ss, 1)


def build_daily_stats(df, full_range=None):
    """
    Compute StdDailyDemand per part, correctly including zero-demand days.

    full_range : pd.DatetimeIndex, optional
        Calendar window to reindex every part onto. If None, uses the
        min/max OrderDate across the whole dataset (same window for
        every part, for cross-part and cross-script comparability).
    """
    daily = df.groupby(["PartNum", "OrderDate"])["RelQty"].sum().reset_index()

    if full_range is None:
        full_range = pd.date_range(df["OrderDate"].min(), df["OrderDate"].max(), freq="D")

    rows = []
    for part_num, g in daily.groupby("PartNum"):
        series = g.set_index("OrderDate")["RelQty"].reindex(full_range, fill_value=0)
        rows.append({
            "PartNum": part_num,
            "StdDailyDemand": series.std(),
            "MeanDailyDemand": series.mean(),  # handy for cross-checking vs forecast script
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_csv("spend_clean.csv", parse_dates=["OrderDate"])

    daily_stats = build_daily_stats(df)
    daily_stats["StdDailyDemand"] = daily_stats["StdDailyDemand"].fillna(0)

    lead_times = (
        df.groupby("PartNum")["LeadTime_PartPlant"]
        .median()
        .reset_index()
        .rename(columns={"LeadTime_PartPlant": "LeadTimeDays"})
    )
    lead_times["LeadTimeDays"] = lead_times["LeadTimeDays"].fillna(30)

    result = daily_stats.merge(lead_times, on="PartNum")
    service_level = 0.95
    result["safety_stock"] = result.apply(
        lambda row: compute_safety_stock(row, service_level=service_level), axis=1
    )
    result["service_level"] = service_level

    result.to_csv("safety_stock_output.csv", index=False)
    print(f"Saved safety_stock_output.csv  ({len(result)} rows)")
    print(result[["PartNum", "StdDailyDemand", "MeanDailyDemand", "LeadTimeDays", "safety_stock"]].head(10).to_string(index=False))