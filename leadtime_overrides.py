"""
leadtime_overrides.py
----------------------
Shared read/write layer for leadtime_overrides.csv — the standing log of
manual Lead Time corrections buyers enter when a part's pipeline Lead Time
is 0 (almost always missing/bad source data, not a genuine same-day lead
time — see 03_safety_stock.py's Site Minimum formula, which zeroes out
regardless of demand volatility whenever LeadTimeDays is 0).

This file is a correction LOG, not a pipeline output: 03_safety_stock.py,
04_ROP.py, and front_end.py all read it, but nothing in the pipeline
re-runs ever overwrite it wholesale — only upsert_override() (called from
serve_dashboard.py's Save Correction endpoint) writes to it, one row at a
time, keyed by part_number.

Columns: part_number, corrected_lead_time, corrected_by, corrected_date, note
"""

import os
from datetime import date

import pandas as pd

OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadtime_overrides.csv")
OVERRIDE_COLUMNS = ["part_number", "corrected_lead_time", "corrected_by", "corrected_date", "note"]


def load_overrides(path=OVERRIDES_PATH):
    """Return the override log as a DataFrame (empty with the right columns if the file doesn't exist yet)."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    df = pd.read_csv(path, dtype={"part_number": str, "corrected_by": str, "corrected_date": str, "note": str})
    df["corrected_lead_time"] = pd.to_numeric(df["corrected_lead_time"], errors="coerce")
    return df


def apply_overrides(
    df,
    part_col="PartNum",
    leadtime_col="LeadTimeDays",
    source_col="LeadTimeSource",
    date_col=None,
    by_col=None,
    path=OVERRIDES_PATH,
):
    """
    Merge manual corrections into df in place of leadtime_col for any matching
    part_number, stamping source_col = "manually corrected" for those rows
    (source_col defaults to "actual" for every other row, added only if the
    column doesn't already exist so an upstream source label, e.g.
    "supplier", is preserved for parts without a manual override).
    """
    df = df.copy()
    if source_col not in df.columns:
        df[source_col] = "actual"
    if date_col and date_col not in df.columns:
        df[date_col] = None
    if by_col and by_col not in df.columns:
        df[by_col] = None

    overrides = load_overrides(path)
    if overrides.empty:
        return df

    overrides = overrides.drop_duplicates(subset="part_number", keep="last").set_index("part_number")
    keys = df[part_col].astype(str)
    mask = keys.isin(overrides.index)
    if not mask.any():
        return df

    matched_keys = keys[mask]
    df.loc[mask, leadtime_col] = matched_keys.map(overrides["corrected_lead_time"]).values
    df.loc[mask, source_col] = "manually corrected"
    if date_col:
        df.loc[mask, date_col] = matched_keys.map(overrides["corrected_date"]).values
    if by_col:
        df.loc[mask, by_col] = matched_keys.map(overrides["corrected_by"]).values
    return df


def upsert_override(part_number, corrected_lead_time, corrected_by, note="", path=OVERRIDES_PATH):
    """Write (or replace) the correction row for one part. Returns the new row as a dict."""
    part_number = str(part_number).strip()
    if not part_number:
        raise ValueError("part_number is required")
    corrected_lead_time = float(corrected_lead_time)
    if corrected_lead_time < 0:
        raise ValueError("corrected_lead_time must be >= 0")

    overrides = load_overrides(path)
    overrides = overrides[overrides["part_number"] != part_number]

    new_row = {
        "part_number": part_number,
        "corrected_lead_time": corrected_lead_time,
        "corrected_by": (corrected_by or "").strip() or "unknown",
        "corrected_date": date.today().isoformat(),
        "note": (note or "").strip(),
    }
    overrides = pd.concat([overrides, pd.DataFrame([new_row])], ignore_index=True)
    overrides = overrides.sort_values("part_number").reset_index(drop=True)
    overrides.to_csv(path, index=False)
    return new_row
