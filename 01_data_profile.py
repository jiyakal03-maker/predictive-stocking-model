"""
01_data_profile.py
------------------
Profiles the raw PO history data before any cleaning.
Run this first to understand data quality before touching anything.

Expected input file: 'Spend History 061026JN.xlsx' in the same folder.
(Update DATA_FILE below if your filename differs.)

What this script checks:
    1. Row/column counts
    2. Column data types
    3. Null counts per column
    4. Date column formats (OrderDate, RelDueDate, LastPODate)
    5. OrderQty vs RelQty consistency
    6. BaseUnitCost vs AdjUnitCost variance
    7. Unique value counts for key categorical columns
    8. Summary statistics for numeric columns
"""

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Config — update filename here if needed
# ---------------------------------------------------------------------------
DATA_FILE = "Spend History 061026JN.xlsx"

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
print("=" * 60)
print("LOADING DATA")
print("=" * 60)

df = pd.read_excel(DATA_FILE)
print(f"Rows: {len(df):,}")
print(f"Columns: {len(df.columns)}")
print(f"\nColumn names:\n{list(df.columns)}")

# ---------------------------------------------------------------------------
# 1. Data types
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("COLUMN DATA TYPES")
print("=" * 60)
print(df.dtypes.to_string())

# ---------------------------------------------------------------------------
# 2. Null counts
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("NULL COUNTS")
print("=" * 60)
null_counts = df.isnull().sum()
null_pct = (null_counts / len(df) * 100).round(1)
null_report = pd.DataFrame({"null_count": null_counts, "null_%": null_pct})
print(null_report[null_report["null_count"] > 0].to_string())
print(f"\nColumns with zero nulls: {(null_counts == 0).sum()}")

# ---------------------------------------------------------------------------
# 3. Date columns
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("DATE COLUMN CHECKS")
print("=" * 60)
date_cols = ["OrderDate", "RelDueDate", "LastPODate"]
for col in date_cols:
    if col in df.columns:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            bad = parsed.isna().sum() - df[col].isna().sum()
            print(f"{col}:")
            print(f"  Min: {parsed.min()}")
            print(f"  Max: {parsed.max()}")
            print(f"  Unparseable (non-null but bad format): {bad}")
        except Exception as e:
            print(f"{col}: ERROR — {e}")

# ---------------------------------------------------------------------------
# 4. OrderQty vs RelQty consistency
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("ORDERQTY vs RELQTY CONSISTENCY")
print("=" * 60)
if "OrderQty" in df.columns and "RelQty" in df.columns:
    both_present = df[["OrderQty", "RelQty"]].dropna()
    mismatch = (both_present["OrderQty"] != both_present["RelQty"]).sum()
    print(f"Rows where OrderQty != RelQty: {mismatch:,} ({mismatch/len(df)*100:.1f}%)")
    print(f"OrderQty stats:\n{df['OrderQty'].describe().round(2)}")
    print(f"\nRelQty stats:\n{df['RelQty'].describe().round(2)}")

# ---------------------------------------------------------------------------
# 5. BaseUnitCost vs AdjUnitCost variance
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("BASECOST vs ADJCOST VARIANCE")
print("=" * 60)
if "BaseUnitCost" in df.columns and "AdjUnitCost" in df.columns:
    cost_df = df[["BaseUnitCost", "AdjUnitCost"]].dropna()
    cost_df = cost_df[cost_df["BaseUnitCost"] > 0]  # avoid divide-by-zero
    cost_df["pct_diff"] = ((cost_df["AdjUnitCost"] - cost_df["BaseUnitCost"]) / cost_df["BaseUnitCost"] * 100).round(2)
    print(f"Rows compared (BaseUnitCost > 0): {len(cost_df):,}")
    print(f"Rows where they differ by >5%: {(cost_df['pct_diff'].abs() > 5).sum():,}")
    print(f"\nPct difference stats:\n{cost_df['pct_diff'].describe().round(2)}")

# ---------------------------------------------------------------------------
# 6. Key categorical columns — unique value counts
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("CATEGORICAL UNIQUE VALUE COUNTS")
print("=" * 60)
cat_cols = ["SupplierSegment", "PartClassID", "PartClass", "CommodityCode",
            "CommodityCodeDesc", "BuyerID", "BuyerName", "BaseUOM"]
for col in cat_cols:
    if col in df.columns:
        n = df[col].nunique()
        top = df[col].value_counts().head(3).to_dict()
        print(f"{col}: {n} unique values | top 3: {top}")

# ---------------------------------------------------------------------------
# 7. Numeric column summary stats
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("NUMERIC SUMMARY STATS")
print("=" * 60)
num_cols = ["RelQty", "OrderQty", "RelExtCost", "BaseUnitCost", "AdjUnitCost",
            "LeadTime_PartPlant", "LeadTime_SPLHead", "LeadTime_SPLDetail"]
for col in num_cols:
    if col in df.columns:
        print(f"\n{col}:\n{df[col].describe().round(2)}")

print("\n" + "=" * 60)
print("PROFILING COMPLETE")
print("=" * 60)
