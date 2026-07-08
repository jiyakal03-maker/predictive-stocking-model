# The mathematically optimal order quantity that minimizes total inventory costs (ordering + holding).
# Depends on demand and cost parameters, so it's not a one-size-fits-all number.

import pandas as pd
import numpy as np

DEFAULT_ORDERING_COST = 50.0
DEFAULT_HOLDING_COST_RATE = 0.25

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
    return df.groupby("PartNum")["AdjUnitCost"].mean().reset_index().rename(columns={"AdjUnitCost": "avg_unit_cost"})

def compute_eoq(df, ordering_cost=DEFAULT_ORDERING_COST, holding_cost_rate=DEFAULT_HOLDING_COST_RATE, cost_overrides=None):
    cost_overrides = cost_overrides or {}
    demand_df = compute_annual_demand(df)
    cost_df = compute_avg_unit_cost(df)
    result = demand_df.merge(cost_df, on="PartNum", how="left")
    result["avg_unit_cost"] = result.apply(lambda row: cost_overrides.get(row["PartNum"], row["avg_unit_cost"]), axis=1)
    result["avg_unit_cost"] = result["avg_unit_cost"].fillna(0)
    result["holding_cost_per_unit"] = (result["avg_unit_cost"] * holding_cost_rate).round(4)

    def eoq_formula(row):
        D, S, H = row["annual_demand"], ordering_cost, row["holding_cost_per_unit"]
        if D <= 0 or H <= 0:
            return np.nan
        return round(np.sqrt((2 * D * S) / H), 2)

    result["eoq"] = result.apply(eoq_formula, axis=1)
    result["orders_per_year"] = (result["annual_demand"] / result["eoq"]).round(2)
    result["avg_cycle_stock"] = (result["eoq"] / 2).round(2)
    result["total_annual_cost"] = ((result["orders_per_year"] * ordering_cost) + (result["avg_cycle_stock"] * result["holding_cost_per_unit"])).round(2)
    result["ordering_cost_assumption"] = ordering_cost
    result["holding_cost_rate"] = holding_cost_rate
    return result[["PartNum","annual_demand","avg_unit_cost","holding_cost_per_unit","eoq","orders_per_year","avg_cycle_stock","total_annual_cost","ordering_cost_assumption","holding_cost_rate"]].copy()

if __name__ == "__main__":
    import random
    random.seed(42)
    np.random.seed(42)

    dates = pd.date_range("2023-01-01", "2024-12-31", freq="W")
    records = []
    part_costs = {"PART-001": 12.50, "PART-002": 4.00, "PART-003": 250.00}

    for part, cost in part_costs.items():
        for d in dates:
            if random.random() > 0.4:
                records.append({
                    "PartNum": part,
                    "OrderDate": d,
                    "RelQty": max(1, int(np.random.normal(50, 10))),
                    "AdjUnitCost": cost * np.random.uniform(0.95, 1.05),
                })

    data = pd.read_csv("spend_clean.csv")
    eoq_df = compute_eoq(data, ordering_cost=50, holding_cost_rate=0.25)
    eoq_df.to_csv("eoq_output.csv", index=False)
    print(f"Saved eoq_output.csv  ({len(eoq_df)} rows)")
    print(eoq_df.to_string(index=False))

    print("\nInterpretation:")
    for _, row in eoq_df.iterrows():
        print(f"  {row['PartNum']}: Order {row['eoq']:.0f} units at a time, ~{row['orders_per_year']:.1f}x/year → ${row['total_annual_cost']:,.2f}/yr total cost")