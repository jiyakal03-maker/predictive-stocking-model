"""
03_safety_stock.py
------------------
Computes Site Minimum (safety stock buffer) for a single part, per Epicor
Kinetic's Site Minimum Calculator.

Formula:
    SiteMinimum = ROUNDUP( Z_abc * StdDailyDemand * sqrt(LeadTimeDays), 0 )

Z is looked up by ABC code only (NOT by XYZ):
    A -> 2.05  (98% service level)
    B -> 1.64  (95% service level)
    C -> 1.28  (90% service level)

StdDailyDemand is the empirical std dev computed from the full zero-filled
demand calendar when a part has enough transaction history. Parts with too
few data points fall back to the workbook's range-based estimate:
    Est. StdDev = (Est. Max Daily Usage - Est. Min Daily Usage) / 4
The method actually used is recorded per part in `stddev_method`
("empirical" or "estimated") for audit purposes.

Input (part_data — dict or pd.Series):
    ABC            : str    ABC classification code ("A", "B", "C")
    StdDailyDemand : float  standard deviation of daily demand
    LeadTimeDays   : float  replenishment lead time in calendar days

Output:
    int — Site Minimum (safety stock) quantity
"""

import math
import pandas as pd

from leadtime_overrides import apply_overrides

Z_FACTORS = {
    "A": 2.05,  # 98% service level
    "B": 1.64,  # 95% service level
    "C": 1.28,  # 90% service level
}

# Parts with fewer distinct demand-days than this fall back to the
# range-based estimate instead of the empirical std dev.
MIN_OBS_FOR_EMPIRICAL_STDDEV = 5


def compute_safety_stock(part_data):
    """Return Site Minimum (safety stock) for one part given ABC code, std dev, and lead time."""
    abc = part_data["ABC"]
    Z = Z_FACTORS.get(abc)
    if Z is None:
        raise ValueError(f"ABC must be one of {list(Z_FACTORS.keys())}. Got {abc!r}.")
    ss = Z * part_data["StdDailyDemand"] * math.sqrt(part_data["LeadTimeDays"])
    return math.ceil(ss)


def build_daily_stats(df, full_range=None):
    """
    Compute StdDailyDemand per part, correctly including zero-demand days,
    with a fallback to the range-based estimate for low-history parts.

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
        observed = g["RelQty"]
        series = g.set_index("OrderDate")["RelQty"].reindex(full_range, fill_value=0)

        n_obs = len(g)
        empirical_std = series.std()
        estimated_std = (observed.max() - observed.min()) / 4

        if n_obs >= MIN_OBS_FOR_EMPIRICAL_STDDEV and pd.notna(empirical_std):
            std_daily = empirical_std
            method = "empirical"
        else:
            std_daily = estimated_std
            method = "estimated"

        rows.append({
            "PartNum": part_num,
            "StdDailyDemand": std_daily,
            "MeanDailyDemand": series.mean(),  # handy for cross-checking vs forecast script
            "stddev_method": method,
            "TransactionDays": n_obs,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_csv("spend_clean.csv", parse_dates=["OrderDate"])
    abc_lookup = pd.read_csv("abc_xyz_matrix.csv")[["PartNum", "ABC"]]

    daily_stats = build_daily_stats(df)
    daily_stats["StdDailyDemand"] = daily_stats["StdDailyDemand"].fillna(0)

    lead_times = (
        df.groupby("PartNum")["LeadTime_PartPlant"]
        .median()
        .reset_index()
        .rename(columns={"LeadTime_PartPlant": "LeadTimeDays"})
    )
    lead_times["LeadTimeDays"] = lead_times["LeadTimeDays"].fillna(30)

    # Apply manual corrections logged in leadtime_overrides.csv (e.g. parts
    # whose LeadTimeDays came back 0 from Epicor because no lead time was
    # ever entered there, not because it's genuinely a same-day part).
    lead_times = apply_overrides(
        lead_times, part_col="PartNum", leadtime_col="LeadTimeDays", source_col="lead_time_source"
    )

    result = daily_stats.merge(lead_times, on="PartNum").merge(abc_lookup, on="PartNum", how="left")
    result["safety_stock"] = result.apply(compute_safety_stock, axis=1)

    result.to_csv("safety_stock_output.csv", index=False)
    print(f"Saved safety_stock_output.csv  ({len(result)} rows)")
    print(result["stddev_method"].value_counts())
    print(result[["PartNum", "ABC", "StdDailyDemand", "stddev_method", "LeadTimeDays", "safety_stock"]].head(10).to_string(index=False))
