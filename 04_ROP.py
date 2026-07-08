"""
04_ROP.py
---------
Calculates Site Minimum for each part, per Epicor Kinetic's Site Minimum
Calculator. This is a safety-stock buffer ONLY — there is no
average-demand-during-lead-time term added on top of it. (An earlier
version of this file computed a classic Reorder Point — avg daily demand *
lead time + safety stock — but that is a different metric than Epicor's
Site Minimum field, so it has been removed. The file keeps its numbered
name for pipeline-chaining purposes; the output is labeled "Site Minimum"
everywhere it surfaces to buyers.)

Formula:
    SiteMinimum = ROUNDUP( Z_abc * StdDailyDemand * sqrt(LeadTimeDays), 0 )

When on-hand inventory hits this number, place a new order.

Depends on: 03_safety_stock.py (must be in the same folder)

Input columns expected in DataFrame:
    - PartNum
    - OrderDate
    - RelQty
    - LeadTime_PartPlant

Output:
    DataFrame with one row per part:
        PartNum | ABC | avg_daily_demand | lead_time_days | StdDailyDemand
        stddev_method | SiteMinimum | lead_time_source
"""

import pandas as pd
from importlib import import_module

from leadtime_overrides import apply_overrides

_ss_module = import_module("03_safety_stock")
compute_safety_stock = _ss_module.compute_safety_stock
build_daily_stats = _ss_module.build_daily_stats


def compute_rop(
    df: pd.DataFrame,
    abc_lookup: pd.DataFrame,
    supplier_lead_times: dict = None,
) -> pd.DataFrame:
    """
    Computes Site Minimum per part.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned PO history DataFrame.
    abc_lookup : pd.DataFrame
        Columns [PartNum, ABC] — ABC classification per part.
    supplier_lead_times : dict, optional
        Override lead times with supplier-actual values.
        Format: { 'PART-001': 45, 'PART-002': 30 }  (days)

    Returns
    -------
    pd.DataFrame
        One row per part with SiteMinimum and supporting fields.
    """
    # Daily demand stats per part (same zero-fill + empirical/estimated
    # fallback logic as 03_safety_stock.py)
    daily_stats = build_daily_stats(df)
    daily_stats["StdDailyDemand"] = daily_stats["StdDailyDemand"].fillna(0)
    daily_stats = daily_stats.rename(columns={"MeanDailyDemand": "avg_daily_demand"})

    # Lead time per part from PO history
    lead_times = (
        df.groupby("PartNum")["LeadTime_PartPlant"]
        .median()
        .reset_index()
        .rename(columns={"LeadTime_PartPlant": "lead_time_days"})
    )
    lead_times["lead_time_days"] = lead_times["lead_time_days"].fillna(30)

    # Apply supplier overrides if provided
    if supplier_lead_times:
        lead_times["lead_time_days"] = lead_times.apply(
            lambda r: supplier_lead_times.get(r["PartNum"], r["lead_time_days"]),
            axis=1,
        )
        lead_times["lead_time_source"] = lead_times["PartNum"].apply(
            lambda p: "supplier" if p in supplier_lead_times else "actual"
        )
    else:
        lead_times["lead_time_source"] = "actual"

    # Manual corrections (leadtime_overrides.csv) win over both the supplier
    # override and the raw historical median — a buyer who's flagged a part
    # as wrong takes precedence over both.
    lead_times = apply_overrides(
        lead_times, part_col="PartNum", leadtime_col="lead_time_days", source_col="lead_time_source"
    )

    policy = (
        daily_stats.merge(lead_times, on="PartNum")
        .merge(abc_lookup, on="PartNum", how="left")
    )

    # Site Minimum via 03_safety_stock.compute_safety_stock (applied per row)
    policy["SiteMinimum"] = policy.apply(
        lambda row: compute_safety_stock({
            "ABC": row["ABC"],
            "StdDailyDemand": row["StdDailyDemand"],
            "LeadTimeDays": row["lead_time_days"],
        }),
        axis=1,
    )

    return policy[[
        "PartNum",
        "ABC",
        "avg_daily_demand",
        "lead_time_days",
        "StdDailyDemand",
        "stddev_method",
        "SiteMinimum",
        "lead_time_source",
    ]]


# ---------------------------------------------------------------------------
# Main method
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data = pd.read_csv("spend_clean.csv", parse_dates=["OrderDate"])
    abc_lookup = pd.read_csv("abc_xyz_matrix.csv")[["PartNum", "ABC"]]

    supplier_overrides = {"PART-003": 45}

    result = compute_rop(
        data,
        abc_lookup,
        supplier_lead_times=supplier_overrides,
    )

    result.to_csv("rop_output.csv", index=False)
    print(f"Saved rop_output.csv  ({len(result)} rows)")
    print(result.head(10).to_string(index=False))
    print("\nInterpretation: When on-hand inventory drops to Site Minimum, place a new order.")
