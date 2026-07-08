# 07_simulation.py
# Phase 5 - Steps 1 & 2: Load demand data and build inventory policy

import pandas as pd
import numpy as np

def load_sample_demand(
    spend_path="spend_clean.csv",
    matrix_path="abc_xyz_matrix.csv",
    n_per_category=100,
    random_state=42
):
    # Load ABC/XYZ matrix and sample
    matrix = pd.read_csv(matrix_path)

    print("ABC/XYZ category counts:")
    print(matrix["ABCXYZ"].value_counts())

    sampled = (
        matrix.groupby("ABCXYZ", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), n_per_category), random_state=random_state))
        .reset_index(drop=True)
    )

    print(f"\nSampled columns: {sampled.columns.tolist()}")
    print(f"Total sampled parts: {len(sampled)}")

    sampled_parts = sampled["PartNum"].unique()

    # Load spend and filter to sampled parts only
    df = pd.read_csv(spend_path, parse_dates=["OrderDate"])
    df = df[df["PartNum"].isin(sampled_parts)]
    print(f"Filtered PO rows: {len(df)}")

    # Aggregate to daily demand
    daily = (
        df.groupby(["PartNum", "OrderDate"])["RelQty"]
        .sum()
        .reset_index()
        .rename(columns={"OrderDate": "Date", "RelQty": "DailyDemand"})
    )

    # Fill in missing days with zero
    all_dates = pd.date_range(daily["Date"].min(), daily["Date"].max(), freq="D")
    all_parts = daily["PartNum"].unique()

    idx = pd.MultiIndex.from_product([all_parts, all_dates], names=["PartNum", "Date"])
    daily = daily.set_index(["PartNum", "Date"]).reindex(idx, fill_value=0).reset_index()

    print(f"Final demand table shape: {daily.shape}")
    return daily, sampled, df


def build_policy(df, sampled):
    # Daily demand stats per part
    daily_stats = (
        df.groupby(["PartNum", "OrderDate"])["RelQty"]
        .sum()
        .reset_index()
        .groupby("PartNum")["RelQty"]
        .agg(AvgDailyDemand="mean", StdDailyDemand="std")
        .reset_index()
    )
    daily_stats["StdDailyDemand"] = daily_stats["StdDailyDemand"].fillna(0)

    # Lead time per part
    lead_times = (
        df.groupby("PartNum")["LeadTime_PartPlant"]
        .median()
        .reset_index()
        .rename(columns={"LeadTime_PartPlant": "LeadTimeDays"})
    )
    lead_times["LeadTimeDays"] = lead_times["LeadTimeDays"].fillna(30)

    # Unit cost per part
    costs = (
        df.groupby("PartNum")["AdjUnitCost"]
        .median()
        .reset_index()
        .rename(columns={"AdjUnitCost": "UnitCost"})
    )

    # Combine
    policy = daily_stats.merge(lead_times, on="PartNum").merge(costs, on="PartNum")

    # Bring in ABCXYZ category from sampled
    category_map = sampled[["PartNum", "ABCXYZ"]].drop_duplicates()
    policy = policy.merge(category_map, on="PartNum", how="left")

    # Safety stock (Z=1.65 = 95% service level)
    Z = 1.65
    policy["SafetyStock"] = (
        Z * policy["StdDailyDemand"] * policy["LeadTimeDays"] ** 0.5
    ).round(1)

    # Reorder point
    policy["ROP"] = (
        policy["AvgDailyDemand"] * policy["LeadTimeDays"] + policy["SafetyStock"]
    ).round(1)

    # EOQ (ordering cost=$50, holding rate=25%)
    ordering_cost = 50
    holding_rate = 0.25
    policy["EOQ"] = (
        (2 * policy["AvgDailyDemand"] * 365 * ordering_cost) /
        (holding_rate * policy["UnitCost"].clip(lower=0.01))
    ) ** 0.5
    policy["EOQ"] = policy["EOQ"].round(1)

    return policy


if __name__ == "__main__":
    # Step 1
    demand, sampled, raw_filtered = load_sample_demand()

    # Step 2
    print("\nBuilding policy...")
    policy = build_policy(raw_filtered, sampled)

    print(f"Policy shape: {policy.shape}")
    print(f"\nSample policy:")
    print(policy[["PartNum","ABCXYZ","AvgDailyDemand","LeadTimeDays","SafetyStock","ROP","EOQ"]].head(10).to_string(index=False))