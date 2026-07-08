"""
04_ROP.py
---------
Calculates the Reorder Point (ROP) for each part.

Formula:
    ROP = (Average Daily Demand * Lead Time in Days) + Safety Stock

When on-hand inventory hits this number, place a new order.

Depends on: 03_safety_stock.py (must be in the same folder)

Input columns expected in DataFrame:
    - PartNum
    - OrderDate
    - RelQty
    - LeadTime_PartPlant

Output:
    DataFrame with one row per part:
        PartNum | avg_daily_demand | lead_time_days | demand_during_lead_time
        safety_stock | ROP | service_level | lead_time_source
"""

import pandas as pd
import numpy as np
from importlib import import_module

_ss_module = import_module("03_safety_stock")
compute_safety_stock = _ss_module.compute_safety_stock


def compute_rop(
    df: pd.DataFrame,
    service_level: float = 0.95,
    supplier_lead_times: dict = None,
) -> pd.DataFrame:
    """
    Computes Reorder Point per part.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned PO history DataFrame.
    service_level : float
        Desired service level. Must be one of: 0.90, 0.95, 0.98, 0.99.
        Default is 0.95.
    supplier_lead_times : dict, optional
        Override lead times with supplier-actual values.
        Format: { 'PART-001': 45, 'PART-002': 30 }  (days)

    Returns
    -------
    pd.DataFrame
        One row per part with ROP and supporting fields.
    """
    # Daily demand stats per part
    # Build daily demand stats with zero-fill (matching 03_safety_stock.py)
    daily = df.groupby(["PartNum", "OrderDate"])["RelQty"].sum().reset_index()
    full_range = pd.date_range(df["OrderDate"].min(), df["OrderDate"].max(), freq="D")
    
    rows = []
    for part_num, g in daily.groupby("PartNum"):
        series = g.set_index("OrderDate")["RelQty"].reindex(full_range, fill_value=0)
        rows.append({
            "PartNum": part_num,
            "avg_daily_demand": series.mean(),
            "std_daily_demand": series.std(),
        })
    daily_stats = pd.DataFrame(rows)
    daily_stats["std_daily_demand"] = daily_stats["std_daily_demand"].fillna(0)

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
            lambda p: "supplier" if p in supplier_lead_times else "historical"
        )
    else:
        lead_times["lead_time_source"] = "historical"

    policy = daily_stats.merge(lead_times, on="PartNum")

    # Safety stock via 03_safety_stock.compute_safety_stock (applied per row)
    policy["safety_stock"] = policy.apply(
        lambda row: compute_safety_stock(
            {"StdDailyDemand": row["std_daily_demand"], "LeadTimeDays": row["lead_time_days"]},
            service_level=service_level,
        ),
        axis=1,
    )

    policy["demand_during_lead_time"] = (
        policy["avg_daily_demand"] * policy["lead_time_days"]
    ).round(2)

    policy["ROP"] = (policy["demand_during_lead_time"] + policy["safety_stock"]).round(2)
    policy["service_level"] = service_level

    return policy[[
        "PartNum",
        "avg_daily_demand",
        "lead_time_days",
        "demand_during_lead_time",
        "safety_stock",
        "ROP",
        "service_level",
        "lead_time_source",
    ]]


# ---------------------------------------------------------------------------
# Main method
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data = pd.read_csv("spend_clean.csv")

    supplier_overrides = {"PART-003": 45}

    result = compute_rop(
        data,
        service_level=0.95,
        supplier_lead_times=supplier_overrides,
    )

    result.to_csv("rop_output.csv", index=False)
    print(f"Saved rop_output.csv  ({len(result)} rows)")
    print(result.to_string(index=False))
    print("\nInterpretation: When on-hand inventory drops to ROP, place a new order.")
