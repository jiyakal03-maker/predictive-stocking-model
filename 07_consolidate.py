"""
07_consolidate.py
------------------
Phase 6: Consolidates outputs from the stocking model pipeline into a single
Excel file for buyers / Power BI. Includes ALL parts with a valid ABC/XYZ
code (A, B, and C) — this used to filter down to A/B only, dropping every
C-tier part.

Inputs:
    - abc_xyz_matrix.csv      (PartNum, ABC, XYZ, ABCXYZ, ...)
    - safety_stock_output.csv (PartNum, StdDailyDemand, stddev_method, LeadTimeDays, safety_stock)
    - rop_output.csv          (PartNum, ABC, avg_daily_demand, lead_time_days, StdDailyDemand,
                                stddev_method, SiteMinimum, lead_time_source)
    - forecast_output.csv     (PartNum, method, part_type, avg_forecasted_monthly_demand)
    - eoq_output.csv          (PartNum, annual_demand, avg_unit_cost, holding_cost_per_unit,
                                eoq, orders_per_year, avg_cycle_stock, total_annual_cost,
                                avg_daily_demand, SiteMinimum, SiteMaximum, ...)

Output:
    - stocking_model_output.xlsx
        Columns: PartNum, ABC, XYZ, ABCXYZ, ForecastedDemand,
                 SiteMinimum, EOQ, SiteMaximum, StdDevMethod, Policy,
                 AvgDailyDemand, StdDevDailyDemand, LeadTimeDays, UnitCost,
                 OrderingCost, HoldingCostRatePct

        The last six columns are the per-part calculator inputs (demand,
        lead time, and cost assumptions) that feed the Part Lookup
        calculator's autofill — without them the calculator can only show
        the same hardcoded example values for every part.
"""

import pandas as pd


def load_csv(path, label):
    df = pd.read_csv(path)
    print(f"  {label:<25} rows={len(df):<8} cols={df.columns.tolist()}")
    return df


def assign_policy(abcxyz: str) -> str:
    if abcxyz in ("AX", "AY", "BX", "BY", "CX", "CY"):
        return "Automated reorder candidate"
    if abcxyz in ("AZ", "BZ"):
        return "Periodic review recommended"
    if abcxyz == "CZ":
        return "Order-only candidate"
    return "Order-only candidate"  # defensive fallback for an unexpected ABC/XYZ code


def main():
    print("=" * 70)
    print("COLUMN AUDIT — names in each CSV before merge")
    print("=" * 70)

    matrix = load_csv("abc_xyz_matrix.csv", "abc_xyz_matrix.csv")
    safety = load_csv("safety_stock_output.csv", "safety_stock_output.csv")
    rop = load_csv("rop_output.csv", "rop_output.csv")
    forecast = load_csv("forecast_output.csv", "forecast_output.csv")
    eoq = load_csv("eoq_output.csv", "eoq_output.csv")

    # Base table = ABC/XYZ matrix (all 9 ABC x XYZ cells — A, B, and C)
    base = matrix[["PartNum", "ABC", "XYZ", "ABCXYZ"]].copy()
    before = len(base)

    # Merge the stddev audit flag (which method 03_safety_stock.py used)
    base = base.merge(
        safety[["PartNum", "stddev_method"]].rename(columns={"stddev_method": "StdDevMethod"}),
        on="PartNum", how="left"
    )

    # Merge Site Minimum (formerly labeled "ROP" — renamed since the formula
    # no longer includes demand-during-lead-time, matching Epicor's Site
    # Minimum Calculator)
    base = base.merge(
        rop[["PartNum", "SiteMinimum"]],
        on="PartNum", how="left"
    )

    # Merge forecast (avg monthly demand)
    base = base.merge(
        forecast[["PartNum", "avg_forecasted_monthly_demand"]].rename(
            columns={"avg_forecasted_monthly_demand": "ForecastedDemand"}
        ),
        on="PartNum", how="left"
    )

    # Merge EOQ and Site Maximum
    base = base.merge(
        eoq[["PartNum", "eoq", "SiteMaximum"]].rename(columns={"eoq": "EOQ"}),
        on="PartNum", how="left"
    )

    # Merge the per-part calculator inputs (demand/lead-time stats from
    # rop_output.csv, cost assumptions from eoq_output.csv). These feed the
    # Part Lookup calculator's autofill — without them every part looks
    # identical there since the calculator falls back to placeholder values.
    base = base.merge(
        rop[["PartNum", "avg_daily_demand", "StdDailyDemand", "lead_time_days", "lead_time_source"]].rename(columns={
            "avg_daily_demand": "AvgDailyDemand",
            "StdDailyDemand": "StdDevDailyDemand",
            "lead_time_days": "LeadTimeDays",
            "lead_time_source": "LeadTimeSource",
        }),
        on="PartNum", how="left"
    )
    base = base.merge(
        eoq[["PartNum", "avg_unit_cost", "ordering_cost_assumption", "holding_cost_rate"]].rename(columns={
            "avg_unit_cost": "UnitCost",
            "ordering_cost_assumption": "OrderingCost",
        }),
        on="PartNum", how="left"
    )
    base["HoldingCostRatePct"] = base["holding_cost_rate"] * 100
    base = base.drop(columns=["holding_cost_rate"])

    print(f"\nTotal parts (A/B/C, all classified): {len(base)} of {before} total rows")

    # Add Policy column — covers all 9 ABC x XYZ combinations
    base["Policy"] = base["ABCXYZ"].apply(assign_policy)

    # Reorder columns
    final_cols = ["PartNum", "ABC", "XYZ", "ABCXYZ", "ForecastedDemand",
                  "SiteMinimum", "EOQ", "SiteMaximum", "StdDevMethod", "Policy",
                  "AvgDailyDemand", "StdDevDailyDemand", "LeadTimeDays", "LeadTimeSource",
                  "UnitCost", "OrderingCost", "HoldingCostRatePct"]
    base = base[final_cols]

    # Save
    out_path = "stocking_model_output.xlsx"
    base.to_excel(out_path, index=False)

    print(f"\nSaved {out_path} — {len(base)} rows")
    print("\nPolicy breakdown:")
    print(base["Policy"].value_counts())

    print("\nNull check per column:")
    print(base.isnull().sum())


if __name__ == "__main__":
    main()