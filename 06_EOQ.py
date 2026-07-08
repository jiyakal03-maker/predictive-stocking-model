# EOQ = the mathematically optimal order quantity that minimizes total inventory costs (ordering + holding).
# Site Maximum = the ceiling inventory level paired with Site Minimum, per Epicor Kinetic's
# Site Maximum Calculator. Both depend on demand and cost parameters, so they're not one-size-fits-all.

import math
import pandas as pd
import numpy as np

FIXED_PO_COST = 100.0      # $ per purchase order
HOLDING_COST_PCT = 0.30    # holding cost, % of accounting value per year
WORKING_DAYS = 250         # working days per year (Site Maximum, EOQ > AnnualDemand branch)
DESIRED_TURNS = 8          # desired inventory turns (Site Maximum, EOQ > AnnualDemand branch)
MIN_ACCOUNTING_VALUE = 0.01  # floor for parts recorded at $0 cost, so EOQ stays finite

def compute_annual_demand(df):
    df = df.copy()
    df["OrderDate"] = pd.to_datetime(df["OrderDate"])
    total = df.groupby("PartNum")["RelQty"].sum().reset_index().rename(columns={"RelQty": "total_qty"})
    date_range = df.groupby("PartNum")["OrderDate"].agg(min_date="min", max_date="max").reset_index()
    date_range["days_of_history"] = (date_range["max_date"] - date_range["min_date"]).dt.days + 1
    date_range["days_of_history"] = date_range["days_of_history"].clip(lower=1)
    merged = total.merge(date_range[["PartNum", "days_of_history"]], on="PartNum")
    merged["annual_demand"] = (merged["total_qty"] / merged["days_of_history"] * 365).round(2)
    return merged[["PartNum", "annual_demand", "days_of_history"]]

def compute_avg_unit_cost(df):
    # Proxy for Epicor's "AccountingValue" field — no separate standard-cost field exists in the PO history.
    return df.groupby("PartNum")["AdjUnitCost"].mean().reset_index().rename(columns={"AdjUnitCost": "avg_unit_cost"})

def compute_eoq(df, ordering_cost=FIXED_PO_COST, holding_cost_rate=HOLDING_COST_PCT, cost_overrides=None):
    cost_overrides = cost_overrides or {}
    demand_df = compute_annual_demand(df)
    cost_df = compute_avg_unit_cost(df)
    result = demand_df.merge(cost_df, on="PartNum", how="left")
    result["avg_unit_cost"] = result.apply(lambda row: cost_overrides.get(row["PartNum"], row["avg_unit_cost"]), axis=1)
    result["avg_unit_cost"] = result["avg_unit_cost"].fillna(0)
    result["holding_cost_per_unit"] = (
        result["avg_unit_cost"].clip(lower=MIN_ACCOUNTING_VALUE) * holding_cost_rate
    ).round(4)

    def eoq_formula(row):
        D, S, H = row["annual_demand"], ordering_cost, row["holding_cost_per_unit"]
        if D <= 0 or H <= 0:
            return np.nan
        return math.ceil(math.sqrt((2 * D * S) / H))

    result["eoq"] = result.apply(eoq_formula, axis=1)
    result["orders_per_year"] = (result["annual_demand"] / result["eoq"]).round(2)
    result["avg_cycle_stock"] = (result["eoq"] / 2).round(2)
    result["total_annual_cost"] = ((result["orders_per_year"] * ordering_cost) + (result["avg_cycle_stock"] * result["holding_cost_per_unit"])).round(2)
    result["ordering_cost_assumption"] = ordering_cost
    result["holding_cost_rate"] = holding_cost_rate
    return result[["PartNum","annual_demand","avg_unit_cost","holding_cost_per_unit","eoq","orders_per_year","avg_cycle_stock","total_annual_cost","ordering_cost_assumption","holding_cost_rate"]].copy()

def compute_site_max(row, working_days=WORKING_DAYS, desired_turns=DESIRED_TURNS):
    """
    Site Maximum, per Epicor Kinetic's Site Maximum Calculator:
        EOQ < AnnualDemand : SiteMax = EOQ + SiteMinimum - 1
        EOQ > AnnualDemand : SiteMax = (AvgDailyDemand * WorkingDays) / DesiredTurns
        EOQ == AnnualDemand: treated as the first branch (edge case)
    """
    eoq, annual_demand = row["eoq"], row["annual_demand"]
    if pd.isna(eoq) or pd.isna(annual_demand) or pd.isna(row["SiteMinimum"]) or pd.isna(row["avg_daily_demand"]):
        return np.nan
    if eoq <= annual_demand:
        return eoq + row["SiteMinimum"] - 1
    return round((row["avg_daily_demand"] * working_days) / desired_turns)

if __name__ == "__main__":
    data = pd.read_csv("spend_clean.csv")
    eoq_df = compute_eoq(data)

    rop = pd.read_csv("rop_output.csv")[["PartNum", "avg_daily_demand", "SiteMinimum"]]
    eoq_df = eoq_df.merge(rop, on="PartNum", how="left")
    eoq_df["SiteMaximum"] = eoq_df.apply(compute_site_max, axis=1)

    eoq_df.to_csv("eoq_output.csv", index=False)
    print(f"Saved eoq_output.csv  ({len(eoq_df)} rows)")
    print(eoq_df.head(10).to_string(index=False))

    print("\nInterpretation:")
    for _, row in eoq_df.head(10).iterrows():
        print(f"  {row['PartNum']}: Order {row['eoq']:.0f} units at a time, ~{row['orders_per_year']:.1f}x/year, Site Max {row['SiteMaximum']:.0f} -> ${row['total_annual_cost']:,.2f}/yr total cost")
