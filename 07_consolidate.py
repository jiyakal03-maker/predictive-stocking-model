"""
07_consolidate.py
------------------
Phase 6: Consolidates outputs from the stocking model pipeline into a single
Excel file for buyers / Power BI.

Inputs:
    - abc_xyz_matrix.csv      (PartNum, ABC, XYZ, ABCXYZ, ...)
    - safety_stock_output.csv (PartNum, StdDailyDemand, LeadTimeDays, safety_stock, service_level)
    - rop_output.csv          (PartNum, avg_daily_demand, lead_time_days, demand_during_lead_time,
                                safety_stock, ROP, service_level, lead_time_source)
    - forecast_output.csv     (PartNum, method, part_type, avg_forecasted_monthly_demand)
    - eoq_output.csv          (PartNum, annual_demand, avg_unit_cost, holding_cost_per_unit,
                                eoq, orders_per_year, avg_cycle_stock, total_annual_cost, ...)

Output:
    - stocking_model_output.xlsx
        Columns: PartNum, ABC, XYZ, ABCXYZ, ForecastedDemand,
                 SafetyStock, ROP, EOQ, Policy
"""

import pandas as pd


def load_csv(path, label):
    df = pd.read_csv(path)
    print(f"  {label:<25} rows={len(df):<8} cols={df.columns.tolist()}")
    return df


def assign_policy(abcxyz: str) -> str:
    if abcxyz in ("AX", "AY", "BX", "BY"):
        return "Automated reorder candidate"
    if abcxyz in ("AZ", "BZ"):
        return "Periodic review recommended"
    return "Manual / order on demand"


def main():
    print("=" * 70)
    print("COLUMN AUDIT — names in each CSV before merge")
    print("=" * 70)

    matrix = load_csv("abc_xyz_matrix.csv", "abc_xyz_matrix.csv")
    safety = load_csv("safety_stock_output.csv", "safety_stock_output.csv")
    rop = load_csv("rop_output.csv", "rop_output.csv")
    forecast = load_csv("forecast_output.csv", "forecast_output.csv")
    eoq = load_csv("eoq_output.csv", "eoq_output.csv")

    # Base table = ABC/XYZ matrix, keep only what we need
    base = matrix[["PartNum", "ABC", "XYZ", "ABCXYZ"]].copy()

    # Merge safety stock (rename to avoid collision with rop's safety_stock)
    base = base.merge(
        safety[["PartNum", "safety_stock"]].rename(columns={"safety_stock": "SafetyStock"}),
        on="PartNum", how="left"
    )

    # Merge ROP
    base = base.merge(
        rop[["PartNum", "ROP"]],
        on="PartNum", how="left"
    )

    # Merge forecast (avg monthly demand)
    base = base.merge(
        forecast[["PartNum", "avg_forecasted_monthly_demand"]].rename(
            columns={"avg_forecasted_monthly_demand": "ForecastedDemand"}
        ),
        on="PartNum", how="left"
    )

    # Merge EOQ
    base = base.merge(
        eoq[["PartNum", "eoq"]].rename(columns={"eoq": "EOQ"}),
        on="PartNum", how="left"
    )

    # Filter to A and B parts only
    before = len(base)
    base = base[base["ABC"].isin(["A", "B"])].copy()
    print(f"\nFiltered to A/B parts: {len(base)} of {before} total rows")

    # Add Policy column
    base["Policy"] = base["ABCXYZ"].apply(assign_policy)

    # Reorder columns
    final_cols = ["PartNum", "ABC", "XYZ", "ABCXYZ", "ForecastedDemand",
                  "SafetyStock", "ROP", "EOQ", "Policy"]
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