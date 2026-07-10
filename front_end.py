# front_end.py — Generates dashboard.html from stocking_model_output.xlsx
# Run: python front_end.py

import pandas as pd
import numpy as np
import json
import webbrowser
from datetime import datetime
from importlib import import_module

from leadtime_overrides import apply_overrides

_ss_module = import_module("03_safety_stock")
_eoq_module = import_module("06_EOQ")
compute_safety_stock = _ss_module.compute_safety_stock
compute_site_max = _eoq_module.compute_site_max

# ── HELPERS ──────────────────────────────────────────────
def safe(v):
    if v is None: return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return round(float(v), 4)
    return v

def df_to_json(df):
    rows = []
    for rec in df.to_dict("records"):
        rows.append({k: (v if isinstance(v, str) else safe(v)) for k, v in rec.items()})
    return json.dumps(rows, default=str)

def fmt_spend(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v == 0:
        return ""
    if v >= 1_000_000:  return f"${v/1_000_000:.1f}M"
    if v >= 1_000:      return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

# ── DATA ─────────────────────────────────────────────────
def recompute_corrected_rows(df):
    """
    For any part whose LeadTimeDays came from a manual override made in the
    Part Lookup tool since the last full 03->07 pipeline run, recompute
    SiteMinimum/SiteMaximum here so the dashboard reflects the correction
    immediately, without waiting on a pipeline re-run. EOQ has no lead-time
    term in its formula (see 06_EOQ.py), so it's left as-is.
    """
    mask = df["LeadTimeSource"] == "manually corrected"
    if not mask.any():
        return df

    df = df.copy()

    def recalc(row):
        try:
            site_min = compute_safety_stock({
                "ABC": row["ABC"],
                "StdDailyDemand": row["StdDevDailyDemand"] or 0,
                "LeadTimeDays": row["LeadTimeDays"],
            })
        except (ValueError, TypeError):
            return pd.Series({"SiteMinimum": row["SiteMinimum"], "SiteMaximum": row["SiteMaximum"]})
        avg_daily = row["AvgDailyDemand"]
        site_max = compute_site_max({
            "eoq": row["EOQ"],
            "annual_demand": (avg_daily or 0) * 365,
            "SiteMinimum": site_min,
            "avg_daily_demand": avg_daily,
        })
        return pd.Series({"SiteMinimum": site_min, "SiteMaximum": site_max})

    df.loc[mask, ["SiteMinimum", "SiteMaximum"]] = df.loc[mask].apply(recalc, axis=1)
    return df


def load_data():
    df = pd.read_excel("stocking_model_output.xlsx")
    for col in ["ForecastedDemand", "SiteMinimum", "EOQ", "SiteMaximum"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Pull spend from abc_xyz_matrix.csv for the matrix display
    try:
        mx = pd.read_csv("abc_xyz_matrix.csv")[["PartNum", "TotalSpend"]]
        df = df.merge(mx, on="PartNum", how="left")
    except Exception:
        df["TotalSpend"] = np.nan

    # Re-apply leadtime_overrides.csv live, on top of whatever the last full
    # pipeline run baked into LeadTimeSource/LeadTimeDays — this is what lets
    # a correction saved in the tool show up immediately for every future
    # load, even before 03->07 is re-run.
    df = apply_overrides(
        df, part_col="PartNum", leadtime_col="LeadTimeDays",
        source_col="LeadTimeSource", date_col="LeadTimeCorrectedDate",
    )
    df = recompute_corrected_rows(df)

    return df

# ── BUILD HTML ───────────────────────────────────────────
def build_html(df):
    N   = len(df)
    now = datetime.now().strftime("%B %d, %Y")

    # Precompute matrix cell stats (static — always shows full dataset)
    mx_data = {}
    for abcxyz, grp in df.groupby("ABCXYZ"):
        spend = grp["TotalSpend"].sum()
        mx_data[abcxyz] = {
            "count": int(len(grp)),
            "spend": fmt_spend(spend) if pd.notna(spend) and spend > 0 else ""
        }
    mx_json = json.dumps(mx_data)

    # Table data (all cols needed by the lookup, table, and calculator autofill)
    keep = ["PartNum", "ABC", "XYZ", "ABCXYZ",
            "ForecastedDemand", "SiteMinimum", "EOQ", "SiteMaximum", "Policy",
            "AvgDailyDemand", "StdDevDailyDemand", "LeadTimeDays",
            "LeadTimeSource", "LeadTimeCorrectedDate",
            "UnitCost", "OrderingCost", "HoldingCostRatePct"]
    data_json = df_to_json(df[[c for c in keep if c in df.columns]])

    # Filter options
    abc_opts    = sorted([str(x) for x in df["ABC"].dropna().unique()])
    xyz_opts    = sorted([str(x) for x in df["XYZ"].dropna().unique()])
    policy_opts = sorted([str(x) for x in df["Policy"].dropna().unique()])

    def pills(items, fkey):
        return "\n".join(
            f'<button class="pill" data-key="{fkey}" data-val="{it}" onclick="togglePill(this)">{it}</button>'
            for it in items)

    # ── CSS ──────────────────────────────────────────────
    CSS = """
:root {
  --bg:      #F3F4F2;
  --card:    #FFFFFF;
  --chdr:    #EDEEEC;
  --accent:  #35617D;
  --accent2: #B7C9D2;
  --primary: #1F3F52;
  --text:    #1B2430;
  --tmid:    #5B6672;
  --tlt:     #5B6672;
  --brd:     #C3C9C5;
  --brdl:    #DBDFDC;
  --topbar:  #1F3F52;
  --amber:   #B9762F;
  --amber-tint: #F7ECDD;
  --good:    #4C7A5E;
  --good-tint: #E7EFEA;
  --bad:     #B14A3E;
  --bad-tint: #F6E7E4;
  --sh:      none;
  --sh-md:   none;
}
*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
body {
  font-family:'IBM Plex Sans', "Segoe UI", system-ui, sans-serif;
  background:var(--bg); color:var(--text);
  min-height:100vh; overflow-y:auto; font-size:14px; line-height:1.45;
}
.mono, .lookup-input, .calc-field input, .calc-field select,
.result-val, .cc-val, .fexpr { font-family:'IBM Plex Mono', monospace; }

/* TOPBAR */
.topbar {
  background:var(--topbar); color:#fff;
  display:flex; align-items:center; justify-content:space-between;
  padding:0 32px; height:52px;
  border-bottom:3px solid var(--accent); position:sticky; top:0; z-index:20;
}
.tb-left { display:flex; align-items:baseline; gap:14px; }
.tb-logo {
  font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.14em;
  color:#9FBBC9; border:1px solid #3E6A82; padding:3px 6px; border-radius:2px;
  background:transparent; font-weight:600;
}
.tb-title { font-size:16px; font-weight:600; letter-spacing:.01em; }
.tb-sub { font-size:12px; color:#B7C9D2; margin-left:4px; }
.tb-right { font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:#B7C9D2; display:flex; gap:18px; }

/* NAV TABS */
.tabs {
  display:flex; gap:2px; padding:0 28px;
  background:var(--card); border-bottom:1px solid var(--brdl);
}
.tab-btn {
  font-family:'IBM Plex Sans',sans-serif; font-size:13px; font-weight:500;
  color:var(--tmid); background:none; border:none;
  padding:13px 16px 11px; cursor:pointer;
  border-bottom:2px solid transparent; letter-spacing:.01em;
}
.tab-btn:hover { color:var(--text); }
.tab-btn.active { color:var(--primary); border-bottom:2px solid var(--accent); font-weight:600; }

/* PAGE */
.page { max-width:1160px; margin:0 auto; padding:24px 28px 60px; display:flex; flex-direction:column; gap:28px; }
.view { display:none; }
.view.active { display:flex; flex-direction:column; gap:28px; }

/* SECTION LABEL */
.sec-label {
  font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:1px; color:var(--tlt); margin-bottom:8px;
}
.page-head h2 { font-size:15px; margin:0 0 3px; font-weight:600; }
.page-head p { margin:0; color:var(--tlt); font-size:13px; max-width:720px; }

/* CARD */
.card {
  background:var(--card); border-radius:3px;
  border:1px solid var(--brdl); box-shadow:var(--sh);
}
.card-hdr {
  padding:12px 16px; background:var(--card);
  border-bottom:1px solid var(--brdl);
  font-size:12px; font-weight:600; color:var(--tmid);
  text-transform:uppercase; letter-spacing:.08em;
}

/* ── LOOKUP GRID (Inputs left / Outputs right) ── */
.lookup-grid { display:grid; grid-template-columns:340px 1fr; gap:20px; align-items:start; }
@media (max-width:900px) { .lookup-grid { grid-template-columns:1fr; } }
.panel { background:var(--card); border:1px solid var(--brdl); border-radius:3px; }
.panel-head {
  padding:12px 16px; border-bottom:1px solid var(--brdl);
  font-size:12px; text-transform:uppercase; letter-spacing:.08em;
  font-weight:600; color:var(--tlt);
}
.panel-body { padding:16px; }
.status-pill {
  display:inline-block; margin-top:8px; font-size:11px; font-weight:600;
  padding:2px 10px; border-radius:20px; background:var(--amber-tint); color:var(--amber);
}
.status-pill.auto     { background:var(--good-tint); color:var(--good); }
.status-pill.periodic { background:var(--amber-tint); color:var(--amber); }
.status-pill.manual   { background:var(--chdr); color:var(--tmid); }

/* ── MATRIX / HEATMAP ───────────────────────── */
.mx-wrap { padding:14px; }
.mx-grid {
  display:grid;
  grid-template-columns:60px repeat(3,1fr);
  gap:10px;
  max-width:900px;
}
.mx-hdr-cell {
  background:transparent; color:var(--tlt);
  font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:.06em; padding:4px 0; text-align:center;
  display:flex; align-items:center; justify-content:center;
}
.mx-side-cell {
  writing-mode:vertical-rl; text-orientation:mixed; transform:rotate(180deg);
  font-size:11px; color:var(--tlt); font-weight:600; text-transform:uppercase;
  letter-spacing:.06em; text-align:center; padding:4px 0;
  display:flex; align-items:center; justify-content:center;
}
.mx-data-cell {
  border-radius:3px; padding:16px;
  display:flex; flex-direction:column;
  justify-content:space-between;
  min-height:92px; color:#fff;
  transition:transform .1s;
}
.mx-data-cell:hover { transform:scale(1.02); }
.cx-key   { font-family:'IBM Plex Mono',monospace; font-size:11px; opacity:.85; }
.cx-count { font-size:22px; font-weight:600; margin:4px 0 2px; }
.cx-spend { font-size:11px; opacity:.85; }
/* Cell colors — darkest = highest priority */
.cAX { background:#152A38; }
.cAY { background:#1E3E4E; }
.cAZ { background:#2A5468; }
.cBX { background:#3D6C80; }
.cBY { background:#5386A0; }
.cBZ { background:#6FA0BC; }
.cCX { background:#8FB8CE; color:#16303F; }
.cCY { background:#B0D0E0; color:#16303F; }
.cCZ { background:#D2E5EE; color:#16303F; }
.cempty { background:var(--chdr); color:var(--tlt); }

/* ── DEFINITION STRIPS ──────────────────────── */
.def-strip { margin-top:16px; display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
@media (max-width:900px) { .def-strip { grid-template-columns:repeat(2,1fr); } }
.def-strip .def-item { font-size:11.5px; color:var(--tlt); padding-left:10px; border-left:2px solid var(--brd); }
.def-strip .def-item b { display:block; color:var(--text); font-size:12px; margin-bottom:2px; }

/* ── PART LOOKUP ────────────────────────────── */
.lookup-body { padding:0; display:flex; flex-direction:column; gap:14px; }
.lookup-input-row { display:flex; gap:10px; align-items:center; }
.lookup-input {
  flex:1; padding:8px 10px; border-radius:3px;
  border:1px solid var(--brd); background:#fff;
  font-size:13px; color:var(--text); outline:none;
  transition:border-color .15s;
}
.lookup-input:focus { outline:2px solid var(--accent); outline-offset:-1px; border-color:var(--accent); }
.lookup-clear {
  padding:8px 14px; border-radius:3px;
  border:1px solid var(--brd); background:transparent;
  color:var(--tmid); font-size:12px; cursor:pointer;
  transition:all .15s; white-space:nowrap;
}
.lookup-clear:hover { border-color:var(--accent); color:var(--accent); }
.field-label {
  display:block; font-size:11px; font-weight:600; color:var(--tlt);
  text-transform:uppercase; letter-spacing:.05em; margin-bottom:5px;
}

/* Result card */
.result-card { display:none; }
.result-card.visible { display:block; }
.result-header {
  padding:0 0 12px; display:flex; align-items:center; gap:10px;
}
.result-partnum { font-size:16px; font-weight:700; color:var(--primary); font-family:'IBM Plex Mono',monospace; }
.result-class-badge {
  background:var(--accent); color:#fff;
  padding:3px 10px; border-radius:2px;
  font-size:11px; font-weight:700; font-family:'IBM Plex Mono',monospace;
}

/* metric cards (used by both Lookup result + Calculator output) */
.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:6px; }
@media (max-width:900px) { .metric-grid { grid-template-columns:repeat(2,1fr); } }
.calc-results { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:6px; }
@media (max-width:900px) { .calc-results { grid-template-columns:repeat(2,1fr); } }
.calc-card, .metric-card {
  background:var(--card); border:1px solid var(--brdl); border-radius:3px; padding:14px 16px;
}
.calc-card .cc-lbl, .metric-card .label {
  font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--tlt); font-weight:600;
}
.calc-card .cc-val, .metric-card .value {
  font-family:'IBM Plex Mono',monospace; font-size:24px; font-weight:600;
  color:var(--primary); margin:6px 0 2px; display:block;
}
.calc-card .cc-unit, .metric-card .unit { font-size:11px; color:var(--tlt); font-weight:400; }
.calc-card .calc-note, .metric-card .def {
  font-size:11.5px; color:var(--tlt); border-top:1px solid var(--brdl);
  margin-top:10px; padding-top:8px; line-height:1.4;
}
.result-row { display:none; } /* legacy list rows, superseded by metric-grid */

/* Lead time result row (kept as a distinct row below the metric grid) */
.lt-row {
  display:flex; align-items:center; gap:8px;
  padding:10px 0; border-top:1px solid var(--brdl); margin-top:4px;
  font-size:13px;
}
.lt-row .lt-lbl { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; color:var(--tlt); width:110px; }
.lt-row .result-val { font-size:14px; font-weight:600; color:var(--text); }
.result-unit { font-size:11px; color:var(--tlt); margin-left:5px; font-weight:400; }
.result-policy-badge {
  display:inline-block; padding:3px 10px;
  border-radius:20px; font-size:11px; font-weight:700;
}
.badge-auto     { background:var(--good-tint); color:var(--good); }
.badge-periodic { background:var(--amber-tint); color:var(--amber); }
.badge-manual   { background:var(--chdr); color:var(--tmid); }
.no-result {
  display:none; padding:14px 0;
  color:var(--tlt); font-size:13px; font-style:italic;
}
.no-result.visible { display:block; }

/* ── LEAD TIME WARNING / CORRECTION ─────────── */
.lt-warning {
  display:none; margin:0 0 12px; padding:10px 14px;
  border-radius:3px; background:var(--bad-tint); color:var(--bad);
  font-size:12.5px; font-weight:600; line-height:1.4;
}
.lt-warning.visible { display:block; }
.lt-indicator { font-size:11px; color:var(--tlt); margin-left:6px; font-weight:400; font-style:italic; }
.lt-edit-block { padding:14px 0 0; border-top:1px solid var(--brdl); margin-top:14px; }
.lt-edit-row { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
.lt-edit-row .calc-field { flex:1; min-width:140px; }
.lt-edit-row .calc-field.lt-by-field { flex:0 0 120px; }
.lt-save-status { margin-top:8px; }
.lt-save-status.flag-good { display:inline-block; padding:4px 10px; border-radius:3px; background:var(--good-tint); color:var(--good); }
.lt-save-status.flag-bad  { display:inline-block; padding:4px 10px; border-radius:3px; background:var(--bad-tint); color:var(--bad); }

/* ── MODE TOGGLE (Lookup / Calculator segmented control) ── */
.mode-toggle { display:inline-flex; border:1px solid var(--brd); border-radius:3px; overflow:hidden; }
.mode-btn {
  padding:6px 14px; border-radius:0;
  border:none; background:#fff;
  color:var(--tmid); font-size:12px; font-weight:600; cursor:pointer;
  transition:all .15s;
}
.mode-btn:hover { color:var(--accent); }
.mode-btn.active { background:var(--accent); color:#fff; }

/* ── CALCULATOR MODE ────────────────────────── */
.calc-body { display:none; flex-direction:column; gap:16px; }
.calc-body.visible { display:flex; }
.calc-grid { display:grid; grid-template-columns:1fr; gap:14px; }
.calc-field label {
  font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.05em;
  color:var(--tlt); display:block; margin-bottom:5px;
}
.calc-field input, .calc-field select {
  width:100%; padding:8px 10px; border-radius:3px;
  border:1px solid var(--brd); background:#fff; font-size:13px; color:var(--text);
}
.calc-field input:focus, .calc-field select:focus { outline:2px solid var(--accent); outline-offset:-1px; border-color:var(--accent); }
.calc-policy {
  display:inline-block; padding:2px 10px; border-radius:20px;
  font-size:11px; font-weight:600; background:var(--amber-tint); color:var(--amber);
}
.calc-xyz-select {
  margin-left:8px; width:auto; display:inline-block;
  padding:4px 8px; border-radius:3px; border:1px solid var(--brd); font-size:11px;
}
.compare-toggle {
  display:flex; align-items:center; gap:6px; cursor:pointer;
  font-size:12px; font-weight:600; color:var(--primary); user-select:none;
}
.compare-body { display:none; margin-top:10px; }
.compare-body.open { display:block; }
.delta-row {
  display:grid; grid-template-columns:1.3fr 1fr 1fr .8fr;
  gap:8px; align-items:center; font-size:12.5px;
  padding:9px 0; border-bottom:1px solid var(--brdl);
  font-family:'IBM Plex Mono',monospace;
}
.delta-row:first-child { font-family:'IBM Plex Sans',sans-serif; }
.delta-row:last-child { border-bottom:none; }
.flag { font-family:'IBM Plex Sans',sans-serif; font-size:11px; font-weight:600; padding:3px 9px; border-radius:20px; text-align:center; }
.flag-good { background:var(--good-tint); color:var(--good); }
.flag-warn { background:var(--amber-tint); color:var(--amber); }
.flag-bad  { background:var(--bad-tint); color:var(--bad); }
.calc-actions { display:flex; gap:10px; flex-wrap:wrap; }
.calc-btn { padding:9px 16px; border-radius:3px; border:none; font-size:12.5px; font-weight:600; cursor:pointer; }
.calc-btn-primary { background:var(--primary); color:#fff; }
.calc-btn-primary:hover { opacity:.9; }
.calc-btn-secondary { background:var(--chdr); color:var(--primary); }
.calc-btn-secondary:hover { background:var(--brd); }
.calc-log-empty { font-size:12px; color:var(--tlt); padding:8px 0; }
.calc-note { font-size:11px; color:var(--tlt); margin-top:2px; }
.calc-section-lbl {
  font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:.06em; color:var(--tlt); margin-top:4px;
}
.calc-log-table { width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }
.calc-log-table th {
  text-align:left; padding:6px 8px; font-size:10px; font-weight:700;
  text-transform:uppercase; color:var(--tmid); border-bottom:2px solid var(--brd);
}
.calc-log-table td { padding:6px 8px; border-bottom:1px solid var(--brdl); font-family:'IBM Plex Mono',monospace; }
.calc-del-btn {
  padding:3px 8px; border-radius:3px; border:1px solid var(--brd);
  background:var(--bg); color:var(--tmid); font-size:11px; cursor:pointer;
}
.calc-del-btn:hover { border-color:var(--accent); color:var(--accent); }

/* ── SPEC PLATE (methodology / formulas) ────── */
.spec-toggle {
  margin-top:4px; background:none; border:1px dashed var(--brd); border-radius:3px;
  width:100%; text-align:left; padding:10px 14px;
  font-family:'IBM Plex Sans',sans-serif; font-size:12.5px; font-weight:600;
  color:var(--primary); cursor:pointer;
  display:flex; align-items:center; justify-content:space-between;
}
.spec-toggle:hover { border-color:var(--accent); }
.spec-toggle .chev { transition:transform .15s ease; }
.spec-toggle.open .chev { transform:rotate(180deg); }
.spec-plate {
  margin-top:10px; background:var(--topbar); border-radius:3px; color:#EAF1F4;
  padding:20px 22px 22px; display:none;
}
.spec-plate.open { display:block; }
.spec-plate h4 {
  margin:0 0 4px; font-size:11px; text-transform:uppercase;
  letter-spacing:.14em; color:#9FBBC9; font-weight:600;
}
.spec-plate .lede { font-size:12.5px; color:#CFE0E7; max-width:680px; margin:0 0 16px; line-height:1.5; }
.formula-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
@media (max-width:760px) { .formula-grid { grid-template-columns:1fr; } }
.formula-row { background:#16303F; border:1px solid #2C5164; border-radius:2px; padding:10px 12px; }
.formula-row .fname {
  font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:#8FADBA; font-weight:600; margin-bottom:4px;
}
.formula-row .fexpr { font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:#EAF1F4; }
.disclaimer { font-size:11.5px; color:#B7C9D2; border-top:1px solid #2C5164; padding-top:12px; line-height:1.5; }
.disclaimer strong { color:#F2C185; }

/* ── TABLE SECTION ──────────────────────────── */
.tbl-filters {
  display:flex; flex-wrap:wrap; gap:8px;
  align-items:center; padding:0 0 14px;
}
.flt-group { display:flex; align-items:center; gap:6px; }
.flt-label {
  font-size:9.5px; font-weight:700; text-transform:uppercase;
  letter-spacing:.7px; color:var(--tlt); white-space:nowrap;
}
.pill-row { display:flex; gap:4px; flex-wrap:wrap; }
.pill {
  padding:5px 12px; border-radius:20px;
  border:1px solid var(--brd); background:#fff;
  color:var(--tmid); font-size:12px; font-weight:500; cursor:pointer; transition:all .15s;
}
.pill:hover  { border-color:var(--accent); color:var(--accent); }
.pill.active { background:var(--primary); border-color:var(--primary); color:#fff; font-weight:600; }
.tbl-search {
  margin-left:auto; padding:7px 12px; border-radius:20px;
  border:1px solid var(--brd); background:#fff;
  font-size:12.5px; outline:none; width:220px; font-family:'IBM Plex Sans',sans-serif;
}
.tbl-search:focus { border-color:var(--accent); }

.fbar {
  padding:7px 0; font-size:11.5px; color:var(--tmid);
  display:flex; align-items:center; gap:8px; flex-wrap:wrap;
}
.fbar strong { color:var(--primary); }
.ftag {
  background:var(--accent); color:#fff;
  padding:1px 7px; border-radius:9px; font-size:10.5px; font-weight:600;
}

.tbl-wrap {
  overflow-x:auto; max-height:460px; overflow-y:auto;
  background:var(--card); border:1px solid var(--brdl); border-radius:3px;
}
.tbl-wrap::-webkit-scrollbar { height:4px; width:4px; }
.tbl-wrap::-webkit-scrollbar-thumb { background:var(--brd); }
table { width:100%; border-collapse:collapse; font-size:13px; }
thead th {
  position:sticky; top:0; z-index:2;
  background:var(--chdr); padding:10px 14px;
  text-align:left; font-size:11px; font-weight:600;
  text-transform:uppercase; letter-spacing:.05em; color:var(--tlt);
  border-bottom:1px solid var(--brdl); cursor:pointer; white-space:nowrap;
  user-select:none;
}
thead th:hover { color:var(--accent); }
.si { font-size:9px; margin-left:2px; color:var(--tlt); }
tbody tr { border-bottom:1px solid var(--brdl); transition:background .1s; cursor:pointer; }
tbody tr:hover { background:var(--chdr); }
tbody td { padding:9px 14px; white-space:nowrap; font-family:'IBM Plex Mono',monospace; }
tbody td:first-child { font-family:'IBM Plex Sans',sans-serif; }
.badge-cls {
  font-family:'IBM Plex Mono',monospace;
  display:inline-block; padding:2px 7px; border-radius:2px;
  font-size:11px; font-weight:600;
  background:var(--chdr); color:var(--primary);
}
.bc-A, .bc-B, .bc-C { background:var(--chdr); color:var(--primary); }
.tbl-foot {
  padding:9px 0 0; display:flex; align-items:center;
  justify-content:space-between;
  font-size:12px; color:var(--tmid);
}
.pgn { display:flex; gap:5px; align-items:center; }
.pbtn {
  padding:3px 9px; border-radius:3px;
  border:1px solid var(--brd); background:var(--bg);
  color:var(--tmid); font-size:12px; cursor:pointer;
}
.pbtn:hover  { border-color:var(--accent); color:var(--accent); }
.pbtn.active { background:var(--primary); border-color:var(--primary); color:#fff; font-weight:600; }
.pbtn:disabled { opacity:.4; cursor:default; }

/* ── FOOTER ─────────────────────────────────── */
footer.status {
  font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--tlt);
  padding:10px 28px; border-top:1px solid var(--brdl); background:var(--card);
}
"""

    # ── JS ────────────────────────────────────────────────
    JS = f"""
const ALL_DATA = {data_json};
const MX_DATA  = {mx_json};

// ── MATRIX (static — shows full dataset always) ───────────
function buildMatrix() {{
  const CELLS = [
    ["AX","AY","AZ"],
    ["BX","BY","BZ"],
    ["CX","CY","CZ"],
  ];
  const X_HDR = ["Stable&nbsp;(X)","Moderate&nbsp;(Y)","Volatile&nbsp;(Z)"];
  const A_HDR = ["A","B","C"];
  const grid  = document.getElementById("mxgrid");
  let h = "";

  // header row
  h += `<div></div>`;
  X_HDR.forEach(l => h += `<div class="mx-hdr-cell">${{l}}</div>`);

  CELLS.forEach((row, ri) => {{
    h += `<div class="mx-side-cell">${{A_HDR[ri]}}</div>`;
    row.forEach(key => {{
      const d = MX_DATA[key] || {{ count:0, spend:"" }};
      const empty = d.count === 0 ? " cempty" : "";
      h += `<div class="mx-data-cell c${{key}}${{empty}}">
        <div class="cx-key">${{key}}</div>
        <div class="cx-count">${{d.count.toLocaleString()}}</div>
        ${{d.spend ? `<div class="cx-spend">${{d.spend}}</div>` : ""}}
      </div>`;
    }});
  }});

  grid.innerHTML = h;
}}

// ── PART LOOKUP ───────────────────────────────────────────
function buildDatalist() {{
  const dl = document.getElementById("part-list");
  ALL_DATA.forEach(d => {{
    const opt = document.createElement("option");
    opt.value = d.PartNum;
    dl.appendChild(opt);
  }});
}}

function lookupPart(val) {{
  const q = (val||"").trim().toLowerCase();
  const result = document.getElementById("lookup-result");
  const noRes  = document.getElementById("no-result");
  if (!q) {{
    result.classList.remove("visible");
    noRes.classList.remove("visible");
    return;
  }}
  const part = ALL_DATA.find(d => (d.PartNum||"").toLowerCase() === q);
  if (part) {{
    noRes.classList.remove("visible");
    showResult(part);
    result.classList.add("visible");
  }} else {{
    result.classList.remove("visible");
    noRes.classList.add("visible");
  }}
}}

let currentLookupPart = null;

function showResult(p) {{
  currentLookupPart = p;
  document.getElementById("res-partnum").textContent = p.PartNum || "—";
  document.getElementById("res-class").textContent   = p.ABCXYZ  || "—";

  const fmtN = v => v != null ? Number(v).toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:2}}) : "—";
  document.getElementById("res-fd").textContent      = fmtN(p.ForecastedDemand);
  document.getElementById("res-sitemin").textContent = fmtN(p.SiteMinimum);
  document.getElementById("res-eoq").textContent     = fmtN(p.EOQ);
  document.getElementById("res-sitemax").textContent = fmtN(p.SiteMaximum);

  const pol = p.Policy || "—";
  const lc  = pol.toLowerCase();
  const cls = lc.includes("automated") ? "auto" : lc.includes("periodic") ? "periodic" : "manual";
  const polEl = document.getElementById("res-policy");
  polEl.textContent  = pol;
  polEl.className    = `result-policy-badge badge-${{cls}}`;

  // Header color by ABC
  const hdr = document.getElementById("result-header");
  const abc = (p.ABC||"").toUpperCase();
  hdr.style.background = "transparent";

  renderLeadTime(p);
}}

function isMissingLeadTime(p) {{
  return p.LeadTimeDays == null || Number(p.LeadTimeDays) === 0;
}}

function renderLeadTime(p) {{
  const missing = isMissingLeadTime(p);
  document.getElementById("res-lt").textContent = p.LeadTimeDays != null ? Number(p.LeadTimeDays).toLocaleString("en-US",{{maximumFractionDigits:2}}) : "—";
  document.getElementById("lt-warning").classList.toggle("visible", missing);

  const indicator = document.getElementById("res-lt-indicator");
  if (p.LeadTimeSource === "manually corrected" && p.LeadTimeCorrectedDate) {{
    indicator.textContent = `(manually corrected on ${{p.LeadTimeCorrectedDate}})`;
  }} else {{
    indicator.textContent = "";
  }}

  document.getElementById("lt-input").value = p.LeadTimeDays != null ? p.LeadTimeDays : "";
  const byInput = document.getElementById("lt-by");
  if (!byInput.value) byInput.value = localStorage.getItem("lt-corrected-by") || "";
  document.getElementById("lt-save-status").textContent = "";
  document.getElementById("lt-save-status").className = "calc-note lt-save-status";
}}

function clearLookup() {{
  document.getElementById("lookup-input").value = "";
  document.getElementById("lookup-result").classList.remove("visible");
  document.getElementById("no-result").classList.remove("visible");
  currentLookupPart = null;
}}

// ── TABLE FILTERS ─────────────────────────────────────────
const F = {{ ABC:new Set(), XYZ:new Set(), Policy:new Set(), search:"" }};
let filteredData = [...ALL_DATA];

function applyFilters() {{
  const s = F.search.toLowerCase();
  filteredData = ALL_DATA.filter(d => {{
    if (F.ABC.size    && !F.ABC.has(d.ABC))       return false;
    if (F.XYZ.size    && !F.XYZ.has(d.XYZ))       return false;
    if (F.Policy.size && !F.Policy.has(d.Policy))  return false;
    if (s && !(d.PartNum||"").toLowerCase().includes(s)) return false;
    return true;
  }});
  tblData = filteredData; tblPage = 0;
  updateFilterBar();
  renderTbl();
}}

function togglePill(btn) {{
  const {{key,val}} = btn.dataset;
  if (F[key].has(val)) {{ F[key].delete(val); btn.classList.remove("active"); }}
  else                 {{ F[key].add(val);    btn.classList.add("active"); }}
  applyFilters();
}}

function onTblSearch(v) {{ F.search = v.trim(); applyFilters(); }}

function updateFilterBar() {{
  document.getElementById("showing").textContent = filteredData.length.toLocaleString();
  const tags = [];
  ["ABC","XYZ","Policy"].forEach(k => {{ if (F[k].size) tags.push(`${{k}}: ${{[...F[k]].join(", ")}}`); }});
  if (F.search) tags.push(`"${{F.search}}"`);
  document.getElementById("atags").innerHTML =
    tags.map(t => `<span class="ftag">${{t}}</span>`).join(" ");
}}

// Clicking a table row fills the lookup
function rowClick(partNum) {{
  const inp = document.getElementById("lookup-input");
  inp.value = partNum;
  lookupPart(partNum);
  inp.scrollIntoView({{behavior:"smooth", block:"center"}});
}}

// ── TABLE ─────────────────────────────────────────────────
const TCOLS = [
  {{ key:"PartNum",          label:"Part #",          w:"160px" }},
  {{ key:"ABCXYZ",           label:"Class",           w:"70px"  }},
  {{ key:"ForecastedDemand", label:"Fcst Demand/Mo",  w:"130px", num:true }},
  {{ key:"SiteMinimum",      label:"Site Min",        w:"90px",  num:true }},
  {{ key:"EOQ",              label:"EOQ",             w:"90px",  num:true }},
  {{ key:"SiteMaximum",      label:"Site Max",        w:"90px",  num:true }},
  {{ key:"Policy",           label:"Policy",          w:"200px" }},
];

let tblData = [...ALL_DATA];
let tblSortKey = "PartNum", tblAsc = true;
let tblPage = 0, PAGE = 25, tblSearch = "";

function buildHead() {{
  document.getElementById("thead").innerHTML = "<tr>" +
    TCOLS.map(c =>
      `<th style="min-width:${{c.w}}" onclick="sortTbl('${{c.key}}')">${{c.label}}<span class="si" id="si-${{c.key}}">⇅</span></th>`
    ).join("") + "</tr>";
}}

function sortTbl(k) {{
  tblSortKey === k ? tblAsc = !tblAsc : (tblSortKey = k, tblAsc = true);
  renderTbl();
}}

function fmtN(v) {{
  if (v == null) return '<span style="color:var(--tlt)">—</span>';
  return Number(v).toLocaleString("en-US", {{minimumFractionDigits:0, maximumFractionDigits:2}});
}}

function clsBadge(val) {{
  if (!val) return '<span style="color:var(--tlt)">—</span>';
  return `<span class="badge-cls bc-${{val[0]}}">${{val}}</span>`;
}}

function renderTbl() {{
  const sorted = [...tblData].sort((a, b) => {{
    const av = a[tblSortKey], bv = b[tblSortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    if (typeof av === "number") return tblAsc ? av-bv : bv-av;
    return tblAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
  }});
  const total = sorted.length, start = tblPage * PAGE;
  const pg = sorted.slice(start, start + PAGE);

  TCOLS.forEach(c => {{
    const el = document.getElementById("si-" + c.key);
    if (el) el.textContent = tblSortKey === c.key ? (tblAsc ? "↑" : "↓") : "⇅";
  }});

  document.getElementById("tbody").innerHTML = pg.map(row =>
    `<tr onclick="rowClick('${{(row.PartNum||"").replace(/'/g,"\\\\'")}}')">${{TCOLS.map(c => {{
      const v = row[c.key];
      let cell;
      if (c.key === "ABCXYZ") cell = clsBadge(v);
      else if (c.key === "Policy") cell = v || '<span style="color:var(--tlt)">—</span>';
      else if (c.num)          cell = fmtN(v);
      else                     cell = v || '<span style="color:var(--tlt)">—</span>';
      return `<td>${{cell}}</td>`;
    }}).join("")}}</tr>`
  ).join("");

  const totalPages = Math.ceil(total / PAGE);
  document.getElementById("tbl-cnt").textContent = total.toLocaleString() + " parts";
  document.getElementById("tbl-range").textContent =
    total === 0 ? "No results"
    : `${{start+1}}–${{Math.min(start+PAGE, total)}} of ${{total.toLocaleString()}}`;

  const pages = [];
  if (totalPages <= 7) {{ for (let i=0; i<totalPages; i++) pages.push(i); }}
  else {{
    pages.push(0);
    if (tblPage > 2) pages.push("…");
    for (let i=Math.max(1,tblPage-1); i<=Math.min(tblPage+1,totalPages-2); i++) pages.push(i);
    if (tblPage < totalPages-3) pages.push("…");
    pages.push(totalPages-1);
  }}
  document.getElementById("pgn").innerHTML =
    `<button class="pbtn" onclick="goPage(${{tblPage-1}})" ${{tblPage===0?"disabled":""}}>‹</button>` +
    pages.map(p => p==="…"
      ? `<span style="color:var(--tlt);padding:0 4px">…</span>`
      : `<button class="pbtn ${{p===tblPage?"active":""}}" onclick="goPage(${{p}})">${{p+1}}</button>`
    ).join("") +
    `<button class="pbtn" onclick="goPage(${{tblPage+1}})" ${{tblPage===totalPages-1||totalPages===0?"disabled":""}}>›</button>`;
}}

function goPage(n) {{ tblPage = n; renderTbl(); }}
""" + """
// ── CALCULATOR MODE ───────────────────────────────────────
// Service factor is looked up by ABC code only (NOT by XYZ), per Epicor Kinetic's
// Site Minimum Calculator.
const Z_FACTORS = { A: 2.05, B: 1.64, C: 1.28 };
const Z_SERVICE_LEVEL = { A: "98%", B: "95%", C: "90%" };
const WORKING_DAYS = 250;
const DESIRED_TURNS = 8;
const STORAGE_AVAILABLE = typeof window.storage !== "undefined";
let memoryCalcLog = [];

// Mirrors 03_safety_stock.compute_safety_stock + 06_EOQ.compute_site_max so
// a Lead Time correction is reflected in Site Min/Max the instant it's
// saved, without waiting on a full pipeline re-run or a page reload.
// EOQ has no lead-time term in its formula, so it's left unchanged.
function recomputeForPart(p, leadTimeDays) {
  const abc = (p.ABC || "").toUpperCase();
  const z = Z_FACTORS[abc] || 0;
  const stdDaily = Number(p.StdDevDailyDemand) || 0;
  const leadTime = Number(leadTimeDays) || 0;
  const siteMin = Math.ceil(z * stdDaily * Math.sqrt(leadTime));

  const avgDaily = Number(p.AvgDailyDemand) || 0;
  const annualDemand = avgDaily * 365;
  const eoq = Number(p.EOQ) || 0;
  const siteMax = eoq <= annualDemand
    ? eoq + siteMin - 1
    : Math.round((avgDaily * WORKING_DAYS) / DESIRED_TURNS);

  return { siteMin, siteMax };
}

async function saveLeadTimeCorrection() {
  const statusEl = document.getElementById("lt-save-status");
  if (!currentLookupPart) {
    statusEl.textContent = "Look up a part first.";
    statusEl.className = "calc-note lt-save-status flag-bad";
    return;
  }
  const partNum = currentLookupPart.PartNum;
  const newLeadTime = parseFloat(document.getElementById("lt-input").value);
  const correctedBy = document.getElementById("lt-by").value.trim();
  if (isNaN(newLeadTime) || newLeadTime < 0) {
    statusEl.textContent = "Enter a valid lead time (0 or more days).";
    statusEl.className = "calc-note lt-save-status flag-bad";
    return;
  }
  if (!correctedBy) {
    statusEl.textContent = "Enter your initials so the correction is attributed.";
    statusEl.className = "calc-note lt-save-status flag-bad";
    return;
  }

  statusEl.textContent = "Saving…";
  statusEl.className = "calc-note lt-save-status";
  try {
    const res = await fetch("/api/save-override", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        part_number: partNum,
        corrected_lead_time: newLeadTime,
        corrected_by: correctedBy,
        note: ""
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `Server responded ${res.status}`);

    localStorage.setItem("lt-corrected-by", correctedBy);

    // Update in-memory data so the fix shows immediately — in this result
    // card, in the browse table, and for the rest of the session — without
    // a reload.
    const { siteMin, siteMax } = recomputeForPart(currentLookupPart, newLeadTime);
    currentLookupPart.LeadTimeDays = newLeadTime;
    currentLookupPart.LeadTimeSource = "manually corrected";
    currentLookupPart.LeadTimeCorrectedDate = data.corrected_date;
    currentLookupPart.SiteMinimum = siteMin;
    currentLookupPart.SiteMaximum = siteMax;

    showResult(currentLookupPart);
    statusEl.textContent = `Saved — Lead Time corrected to ${newLeadTime} days.`;
    statusEl.className = "calc-note lt-save-status flag-good";
    renderTbl();
  } catch (e) {
    statusEl.textContent = `Could not save (${e.message}). Corrections require running the dashboard via serve_dashboard.py, not opening the HTML file directly.`;
    statusEl.className = "calc-note lt-save-status flag-bad";
  }
}

function setMode(mode) {
  const isCalc = mode === "calc";
  document.getElementById("lookup-panel").style.display = isCalc ? "none" : "flex";
  document.getElementById("calc-panel").classList.toggle("visible", isCalc);
  document.getElementById("mode-btn-lookup").classList.toggle("active", !isCalc);
  document.getElementById("mode-btn-calc").classList.toggle("active", isCalc);
  if (isCalc) calcCompute();
}

function cNum(id) {
  const v = parseFloat(document.getElementById(id).value);
  return isNaN(v) ? 0 : v;
}

function calcPolicyFor(abc, xyz) {
  if (!abc || !xyz) return "Select ABC + XYZ";
  const code = abc + xyz;
  if (["AX","AY","BX","BY","CX","CY"].includes(code)) return "Automated reorder candidate";
  if (["AZ","BZ"].includes(code)) return "Periodic review recommended";
  return "Order-only candidate"; // CZ
}

function calcDeltaFlag(manual, pipeline) {
  if (pipeline === 0 || isNaN(pipeline)) return null;
  const pct = Math.abs(manual - pipeline) / Math.abs(pipeline) * 100;
  if (pct <= 5)  return { cls:"flag-good", label:"match" };
  if (pct <= 20) return { cls:"flag-warn", label: pct.toFixed(0) + "% off" };
  return { cls:"flag-bad", label: pct.toFixed(0) + "% off" };
}

function calcCompute() {
  const avgDaily = cNum("c-avgdaily");
  const stdDaily = cNum("c-stddaily");
  const leadTime = cNum("c-leadtime");
  const unitCost = cNum("c-unitcost");
  const orderCost = cNum("c-ordercost");
  const holdRatePct = cNum("c-holdrate");
  const abc = document.getElementById("c-abc").value;
  const z = Z_FACTORS[abc] || 0;

  const zNote = document.getElementById("c-zval");
  zNote.textContent = abc ? `Z = ${z} (${Z_SERVICE_LEVEL[abc]} service level)` : "Select an ABC class to look up Z";

  const forecastMonthly = avgDaily * 30;
  const siteMin = Math.ceil(z * stdDaily * Math.sqrt(leadTime));
  const annualDemand = avgDaily * 365;
  const holdingCostPerUnit = (holdRatePct / 100) * unitCost;
  const eoq = holdingCostPerUnit > 0 && annualDemand > 0
    ? Math.ceil(Math.sqrt((2 * annualDemand * orderCost) / holdingCostPerUnit))
    : 0;
  const siteMax = eoq <= annualDemand
    ? eoq + siteMin - 1
    : Math.round((avgDaily * WORKING_DAYS) / DESIRED_TURNS);

  document.getElementById("c-out-fd").textContent      = forecastMonthly.toFixed(2);
  document.getElementById("c-out-sitemin").textContent = siteMin.toFixed(2);
  document.getElementById("c-out-eoq").textContent     = eoq.toFixed(2);
  document.getElementById("c-out-sitemax").textContent = siteMax.toFixed(2);

  const xyz = document.getElementById("c-xyz").value;
  document.getElementById("c-out-policy").textContent = calcPolicyFor(abc, xyz);

  const calc = { forecastMonthly, siteMin, eoq, siteMax };
  renderCalcDeltas(calc);
  return calc;
}

function renderCalcDeltas(calc) {
  const rows = [
    ["Forecasted demand", calc.forecastMonthly, document.getElementById("c-pfd").value],
    ["Site Minimum",      calc.siteMin,          document.getElementById("c-psitemin").value],
    ["EOQ",               calc.eoq,              document.getElementById("c-peoq").value],
    ["Site Maximum",      calc.siteMax,          document.getElementById("c-psitemax").value],
  ];
  let html = "";
  rows.forEach(([label, manual, rawVal]) => {
    if (rawVal === "") return;
    const pipelineVal = parseFloat(rawVal) || 0;
    const flag = calcDeltaFlag(manual, pipelineVal);
    html += `<div class="delta-row">
      <div>${label}</div>
      <div>calc: ${manual.toFixed(2)}</div>
      <div>pipeline: ${pipelineVal.toFixed(2)}</div>
      <div class="flag ${flag ? flag.cls : ''}">${flag ? flag.label : '—'}</div>
    </div>`;
  });
  document.getElementById("delta-table").innerHTML = html || '<p class="calc-note">Fill in pipeline values above to compare.</p>';
}

function toggleCompare() {
  const body = document.getElementById("compare-body");
  const open = body.classList.toggle("open");
  document.getElementById("compare-arrow").textContent = open ? "▾" : "▸";
}

const CALC_AUTOFILL_IDS = ["c-avgdaily","c-stddaily","c-leadtime","c-unitcost","c-ordercost","c-holdrate"];

function calcSetMatchStatus(cls, text) {
  const el = document.getElementById("c-match-status");
  el.textContent = text;
  el.className = "calc-note" + (cls ? " " + cls : "");
}

function calcAutofillFromPart(val) {
  const q = (val||"").trim().toLowerCase();

  if (!q) {
    // No part number entered — clear the autofilled fields back to the
    // unset placeholder state so they can't be mistaken for real data.
    document.getElementById("c-abc").value = "";
    document.getElementById("c-xyz").value = "";
    CALC_AUTOFILL_IDS.forEach(id => document.getElementById(id).value = "");
    document.getElementById("c-pfd").value = "";
    document.getElementById("c-psitemin").value = "";
    document.getElementById("c-peoq").value = "";
    document.getElementById("c-psitemax").value = "";
    calcSetMatchStatus("", "No part selected — fields below are unset example placeholders, not real data.");
    calcCompute();
    return;
  }

  const part = ALL_DATA.find(d => (d.PartNum||"").toLowerCase() === q);
  if (!part) {
    // Typed value doesn't match any part in the pipeline output — say so
    // explicitly instead of silently leaving stale/placeholder values in
    // place, which would look like a real per-part lookup.
    calcSetMatchStatus("flag-bad", `No pipeline match found for "${val}" — enter values manually.`);
    return;
  }

  document.getElementById("c-abc").value = part.ABC || "";
  document.getElementById("c-xyz").value = part.XYZ || "";
  document.getElementById("c-avgdaily").value = part.AvgDailyDemand ?? "";
  document.getElementById("c-stddaily").value = part.StdDevDailyDemand ?? "";
  document.getElementById("c-leadtime").value = part.LeadTimeDays ?? "";
  document.getElementById("c-unitcost").value = part.UnitCost ?? "";
  document.getElementById("c-ordercost").value = part.OrderingCost ?? "";
  document.getElementById("c-holdrate").value = part.HoldingCostRatePct ?? "";
  document.getElementById("c-pfd").value      = part.ForecastedDemand ?? "";
  document.getElementById("c-psitemin").value = part.SiteMinimum ?? "";
  document.getElementById("c-peoq").value     = part.EOQ ?? "";
  document.getElementById("c-psitemax").value = part.SiteMaximum ?? "";
  calcSetMatchStatus("flag-good", `Autofilled from pipeline data for "${part.PartNum}".`);
  const body = document.getElementById("compare-body");
  if (!body.classList.contains("open")) toggleCompare();
  calcCompute();
}

["c-avgdaily","c-stddaily","c-leadtime","c-unitcost","c-ordercost","c-holdrate",
 "c-abc","c-xyz","c-pfd","c-psitemin","c-peoq","c-psitemax"]
  .forEach(id => document.getElementById(id).addEventListener("input", calcCompute));

async function loadCalcEntries() {
  if (!STORAGE_AVAILABLE) return memoryCalcLog;
  try {
    const result = await window.storage.get("calc-entries", false);
    return result ? JSON.parse(result.value) : [];
  } catch (e) { return []; }
}

async function saveCalcEntries(entries) {
  if (!STORAGE_AVAILABLE) { memoryCalcLog = entries; return; }
  try { await window.storage.set("calc-entries", JSON.stringify(entries), false); }
  catch (e) { console.error("Storage error:", e); }
}

function calcWorstFlag(entry) {
  const flags = [];
  if (entry.pipeline.fd      !== "") flags.push(calcDeltaFlag(entry.calc.forecastMonthly, parseFloat(entry.pipeline.fd)      || 0));
  if (entry.pipeline.sitemin !== "") flags.push(calcDeltaFlag(entry.calc.siteMin,          parseFloat(entry.pipeline.sitemin) || 0));
  if (entry.pipeline.eoq     !== "") flags.push(calcDeltaFlag(entry.calc.eoq,              parseFloat(entry.pipeline.eoq)     || 0));
  if (entry.pipeline.sitemax !== "") flags.push(calcDeltaFlag(entry.calc.siteMax,          parseFloat(entry.pipeline.sitemax) || 0));
  const real = flags.filter(Boolean);
  if (real.some(f => f.cls === "flag-bad"))  return { cls:"flag-bad",  label:"mismatch" };
  if (real.some(f => f.cls === "flag-warn")) return { cls:"flag-warn", label:"close" };
  if (real.length) return { cls:"flag-good", label:"match" };
  return null;
}

async function renderCalcLog() {
  const entries = await loadCalcEntries();
  const container = document.getElementById("calc-log");
  if (!entries.length) {
    container.innerHTML = '<div class="calc-log-empty">No checks saved yet.</div>';
    return;
  }
  const sorted = [...entries].sort((a,b) => b.savedAt - a.savedAt);
  const rows = sorted.map(entry => {
    const flag = calcWorstFlag(entry);
    return `<tr>
      <td>${entry.partNum || "—"}</td>
      <td>${new Date(entry.savedAt).toLocaleDateString()}</td>
      <td>${entry.calc.forecastMonthly.toFixed(2)}</td>
      <td>${entry.calc.siteMin.toFixed(2)}</td>
      <td>${entry.calc.eoq.toFixed(2)}</td>
      <td>${entry.calc.siteMax.toFixed(2)}</td>
      <td>${flag ? `<span class="flag ${flag.cls}">${flag.label}</span>` : "—"}</td>
      <td><button class="calc-del-btn" onclick="deleteCalcEntry(${entry.savedAt})">Delete</button></td>
    </tr>`;
  }).join("");
  container.innerHTML = `<table class="calc-log-table">
    <thead><tr><th>Part #</th><th>Saved</th><th>Forecast</th><th>Site Min</th><th>EOQ</th><th>Site Max</th><th>Check</th><th></th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function deleteCalcEntry(savedAt) {
  const entries = await loadCalcEntries();
  await saveCalcEntries(entries.filter(e => e.savedAt !== savedAt));
  renderCalcLog();
}
window.deleteCalcEntry = deleteCalcEntry;

async function saveCalcCheck() {
  const calc = calcCompute();
  const entry = {
    savedAt: Date.now(),
    partNum: document.getElementById("c-partnum").value,
    calc,
    pipeline: {
      fd:      document.getElementById("c-pfd").value,
      sitemin: document.getElementById("c-psitemin").value,
      eoq:     document.getElementById("c-peoq").value,
      sitemax: document.getElementById("c-psitemax").value
    }
  };
  const entries = await loadCalcEntries();
  entries.push(entry);
  await saveCalcEntries(entries);
  renderCalcLog();
}

function copyCalcRow() {
  const calc = calcCompute();
  const abc = document.getElementById("c-abc").value;
  const xyz = document.getElementById("c-xyz").value;
  const row = [
    document.getElementById("c-partnum").value,
    calc.forecastMonthly.toFixed(2),
    calc.siteMin.toFixed(2),
    calc.eoq.toFixed(2),
    calc.siteMax.toFixed(2),
    calcPolicyFor(abc, xyz)
  ].join("\\t");
  navigator.clipboard.writeText(row).catch(() => {});
}

// ── TABS (new top-level Lookup / ABC-XYZ / Browse nav) ─────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('view-' + btn.dataset.view).classList.add('active');
  });
});

// ── METHODOLOGY / FORMULAS PANEL ────────────────────────────
function toggleSpecPlate() {
  document.getElementById("specToggle").classList.toggle("open");
  document.getElementById("specPlate").classList.toggle("open");
}

// ── TOPBAR CLOCK ─────────────────────────────────────────────
function tickClock() {
  const el = document.getElementById("clock");
  if (el) el.textContent = new Date().toLocaleString("en-US", {hour:"2-digit", minute:"2-digit"});
}
tickClock();
setInterval(tickClock, 30000);

// ── INIT ─────────────────────────────────────────────────
buildMatrix();
buildDatalist();
buildHead();
updateFilterBar();
renderTbl();
calcCompute();
renderCalcLog();
"""

    # ── Policy filter label mapping for display
    def short_policy(p):
        lc = p.lower()
        if "automated" in lc: return "Automated"
        if "periodic"  in lc: return "Periodic"
        return "Manual"

    policy_pills = "\n".join(
        f'<button class="pill" data-key="Policy" data-val="{p}" onclick="togglePill(this)">{short_policy(p)}</button>'
        for p in policy_opts)
    abc_pills = "\n".join(
        f'<button class="pill" data-key="ABC" data-val="{p}" onclick="togglePill(this)">{p}</button>'
        for p in abc_opts)
    xyz_pills = "\n".join(
        f'<button class="pill" data-key="XYZ" data-val="{p}" onclick="togglePill(this)">{p}</button>'
        for p in xyz_opts)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Stocking Model — Etnyre</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>

<!-- TOPBAR -->
<header class="topbar">
  <div class="tb-left">
    <span class="tb-logo">ETNYRE</span>
    <span class="tb-title">Stocking Model — Part Lookup</span>
    <span class="tb-sub">Purchasing &amp; Inventory Analytics</span>
  </div>
  <div class="tb-right">
    <span>{N:,} PARTS</span>
    <span>SOURCE: EPICOR KINETIC</span>
    <span id="clock"></span>
  </div>
</header>

<!-- NAV TABS -->
<nav class="tabs">
  <button class="tab-btn active" data-view="lookup">Part Lookup</button>
  <button class="tab-btn" data-view="abc">ABC / XYZ Overview</button>
  <button class="tab-btn" data-view="browse">Browse All Parts</button>
</nav>

<div class="page">

  <!-- ============ LOOKUP VIEW ============ -->
  <section class="view active" id="view-lookup">
    <div class="page-head">
      <h2>Look up a part or model a hypothetical</h2>
      <p>Enter a part number to pull its pipeline values automatically, or switch to Calculator to test demand, lead time, or cost assumptions before they're loaded into the pipeline.</p>
    </div>

    <div class="card-hdr" style="display:flex;align-items:center;justify-content:space-between;border-radius:3px;border:1px solid var(--brdl);">
      <span>Enter a Part Number</span>
      <div class="mode-toggle">
        <button class="mode-btn active" id="mode-btn-lookup" onclick="setMode('lookup')">Lookup</button>
        <button class="mode-btn" id="mode-btn-calc" onclick="setMode('calc')">Calculator</button>
      </div>
    </div>

    <!-- LOOKUP MODE -->
    <div class="lookup-body" id="lookup-panel">
      <div class="lookup-grid">
        <!-- INPUT PANEL -->
        <div class="panel">
          <div class="panel-head">Part Number</div>
          <div class="panel-body">
            <label class="field-label" for="lookup-input">Part number</label>
            <div class="lookup-input-row">
              <input class="lookup-input" id="lookup-input" type="text"
                list="part-list" placeholder="Type or paste a part number…"
                oninput="lookupPart(this.value)" autocomplete="off">
              <datalist id="part-list"></datalist>
              <button class="lookup-clear" onclick="clearLookup()">✕ Clear</button>
            </div>
            <div class="no-result" id="no-result">No part found with that number.</div>
          </div>
        </div>

        <!-- OUTPUT -->
        <div class="result-card" id="lookup-result">
          <div class="result-header" id="result-header">
            <span class="result-partnum" id="res-partnum"></span>
            <span class="result-class-badge" id="res-class"></span>
            <span class="result-policy-badge" id="res-policy" style="margin-left:auto;"></span>
          </div>
          <div class="lt-warning" id="lt-warning">
            ⚠ No lead time on file for this part — Site Minimum, EOQ, and Site Maximum below are not reliable. Enter a corrected lead time to fix this permanently.
          </div>
          <div class="metric-grid">
            <div class="metric-card">
              <div class="label">Forecasted Demand</div>
              <span class="value" id="res-fd">—</span><span class="unit">units / month</span>
              <div class="def">Simple average — daily demand × 30. A check value, not the moving-average/Holt-Winters model the pipeline actually orders against.</div>
            </div>
            <div class="metric-card">
              <div class="label">Site Minimum</div>
              <span class="value" id="res-sitemin">—</span><span class="unit">units</span>
              <div class="def">Buffer stock held to cover demand variation during lead time.</div>
            </div>
            <div class="metric-card">
              <div class="label">EOQ</div>
              <span class="value" id="res-eoq">—</span><span class="unit">units / order</span>
              <div class="def">Order quantity that minimizes ordering + holding cost together.</div>
            </div>
            <div class="metric-card">
              <div class="label">Site Maximum</div>
              <span class="value" id="res-sitemax">—</span><span class="unit">units</span>
              <div class="def">Ceiling stock level — Site Minimum + EOQ, adjusted for turns.</div>
            </div>
          </div>
          <div class="lt-row">
            <span class="lt-lbl">Lead Time</span>
            <span class="result-val"><span id="res-lt"></span><span class="result-unit">days</span><span class="lt-indicator" id="res-lt-indicator"></span></span>
          </div>
          <div class="lt-edit-block">
            <div class="lt-edit-row">
              <div class="calc-field">
                <label for="lt-input">Corrected lead time (days)</label>
                <input type="number" id="lt-input" min="0" step="any" placeholder="e.g. 45">
              </div>
              <div class="calc-field lt-by-field">
                <label for="lt-by">Corrected by</label>
                <input type="text" id="lt-by" placeholder="initials">
              </div>
              <button class="calc-btn calc-btn-primary" onclick="saveLeadTimeCorrection()">Save Correction</button>
            </div>
            <div class="calc-note lt-save-status" id="lt-save-status"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- CALCULATOR MODE -->
    <div class="calc-body" id="calc-panel">
      <div class="lookup-grid">
        <!-- INPUT PANEL -->
        <div class="panel">
          <div class="panel-head">Calculator Inputs</div>
          <div class="panel-body">
            <div class="calc-grid">
              <div class="calc-field">
                <label for="c-partnum">Part number (optional — autofills pipeline values below if it matches)</label>
                <input type="text" id="c-partnum" list="part-list" placeholder="e.g. 6605173" oninput="calcAutofillFromPart(this.value)" autocomplete="off">
                <span class="calc-note" id="c-match-status">No part selected — fields below are unset example placeholders, not real data.</span>
              </div>
              <div class="calc-field">
                <label for="c-abc">ABC class (looks up Z automatically)</label>
                <select id="c-abc">
                  <option value="">—</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
                </select>
                <span class="calc-note" id="c-zval">Select an ABC class to look up Z</span>
              </div>
              <div class="calc-field">
                <label for="c-avgdaily">Avg daily demand (units/day)</label>
                <input type="number" id="c-avgdaily" step="any" placeholder="e.g. 0.5">
              </div>
              <div class="calc-field">
                <label for="c-stddaily">Std dev of daily demand (units/day)</label>
                <input type="number" id="c-stddaily" step="any" placeholder="e.g. 0.3">
              </div>
              <div class="calc-field">
                <label for="c-leadtime">Lead time (days)</label>
                <input type="number" id="c-leadtime" step="any" placeholder="e.g. 30">
              </div>
              <div class="calc-field">
                <label for="c-unitcost">Unit cost ($)</label>
                <input type="number" id="c-unitcost" step="any" placeholder="e.g. 120">
              </div>
              <div class="calc-field">
                <label for="c-ordercost">Ordering cost per PO ($)</label>
                <input type="number" id="c-ordercost" step="any" placeholder="e.g. 50">
              </div>
              <div class="calc-field">
                <label for="c-holdrate">Holding cost rate (% of unit cost / year)</label>
                <input type="number" id="c-holdrate" step="any" placeholder="e.g. 25">
              </div>
            </div>
          </div>
        </div>

        <!-- OUTPUT -->
        <div>
          <div class="calc-results">
            <div class="calc-card">
              <div class="cc-lbl">Forecasted demand</div>
              <div class="cc-val" id="c-out-fd">—</div><span class="cc-unit">units/mo</span>
              <div class="calc-note">Forecast = AvgDailyDemand × 30 — a check value, not the pipeline's Holt-Winters model.</div>
            </div>
            <div class="calc-card">
              <div class="cc-lbl">Site Minimum</div>
              <div class="cc-val" id="c-out-sitemin">—</div><span class="cc-unit">units</span>
              <div class="calc-note">SiteMin = ROUNDUP(Z × σ × √LT, 0)</div>
            </div>
            <div class="calc-card">
              <div class="cc-lbl">EOQ</div>
              <div class="cc-val" id="c-out-eoq">—</div><span class="cc-unit">units/order</span>
              <div class="calc-note">EOQ = ROUNDUP(√(2×FixedPOCost×AnnualDemand / (HoldingCost% × AccountingValue)), 0)</div>
            </div>
            <div class="calc-card">
              <div class="cc-lbl">Site Maximum</div>
              <div class="cc-val" id="c-out-sitemax">—</div><span class="cc-unit">units</span>
              <div class="calc-note">SiteMax = EOQ+SiteMin−1 if EOQ≤AnnualDemand, else (AvgDailyDemand×WorkingDays)/DesiredTurns</div>
            </div>
          </div>

          <div style="margin:12px 0;">
            <span class="calc-policy" id="c-out-policy">Select ABC + XYZ</span>
            <select id="c-xyz" class="calc-xyz-select">
              <option value="">XYZ —</option><option value="X">X</option><option value="Y">Y</option><option value="Z">Z</option>
            </select>
          </div>

          <div class="panel">
            <div class="panel-head" style="cursor:pointer;" id="compare-toggle" onclick="toggleCompare()">
              <span id="compare-arrow">▸</span> Compare against pipeline values for this part
            </div>
            <div class="compare-body" id="compare-body">
              <div class="panel-body" style="padding-top:12px;">
                <div class="calc-grid" style="grid-template-columns:repeat(2,1fr);">
                  <div class="calc-field"><label for="c-pfd">Pipeline forecast</label><input type="number" id="c-pfd" step="any" placeholder="from dashboard"></div>
                  <div class="calc-field"><label for="c-psitemin">Pipeline Site Minimum</label><input type="number" id="c-psitemin" step="any" placeholder="from dashboard"></div>
                  <div class="calc-field"><label for="c-peoq">Pipeline EOQ</label><input type="number" id="c-peoq" step="any" placeholder="from dashboard"></div>
                  <div class="calc-field"><label for="c-psitemax">Pipeline Site Maximum</label><input type="number" id="c-psitemax" step="any" placeholder="from dashboard"></div>
                </div>
                <div id="delta-table" style="margin-top:8px;"></div>
                <div class="def-strip">
                  <div class="def-item"><b>Green — within 5%</b>Calculator and pipeline agree; no action needed.</div>
                  <div class="def-item"><b>Amber — 5–20% off</b>Worth a glance if you're about to place a PO.</div>
                  <div class="def-item"><b>Red — 20%+ off</b>Usually means the demand input feeding the pipeline differs from what's entered here.</div>
                  <div class="def-item"><b>Not a live edit</b>This check doesn't change the pipeline. Use "Save this check" to log it for review.</div>
                </div>
              </div>
            </div>
          </div>

          <div class="calc-actions" style="margin-top:14px;">
            <button class="calc-btn calc-btn-primary" onclick="saveCalcCheck()">Save this check</button>
            <button class="calc-btn calc-btn-secondary" onclick="copyCalcRow()">Copy row for Excel</button>
          </div>

          <div style="margin-top:14px;">
            <div class="calc-section-lbl">Saved checks</div>
            <div id="calc-log"><div class="calc-log-empty">No checks saved yet.</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- METHODOLOGY / FORMULAS -->
    <button class="spec-toggle" id="specToggle" onclick="toggleSpecPlate()">
      <span>How the forecast is calculated — formulas &amp; disclaimers</span>
      <span class="chev">▾</span>
    </button>
    <div class="spec-plate" id="specPlate">
      <h4>Methodology</h4>
      <p class="lede">The pipeline forecasts demand with a moving-average / Holt-Winters exponential smoothing model fit on each part's order history. The calculator above uses a simpler average-daily-demand × 30 estimate as a fast, transparent check — it will not match the pipeline exactly, and a large gap is itself informative rather than an error.</p>
      <div class="formula-grid">
        <div class="formula-row">
          <div class="fname">Site Minimum</div>
          <div class="fexpr">SiteMin = ROUNDUP(Z × σ × √LT, 0)</div>
        </div>
        <div class="formula-row">
          <div class="fname">Economic Order Qty (EOQ)</div>
          <div class="fexpr">EOQ = ROUNDUP(√(2×FixedPOCost×AnnualDemand ÷ (HoldingCost% × AccountingValue)), 0)</div>
        </div>
        <div class="formula-row">
          <div class="fname">Site Maximum</div>
          <div class="fexpr">SiteMax = EOQ + SiteMin − 1 if EOQ ≤ AnnualDemand, else (AvgDailyDemand × WorkingDays) ÷ DesiredTurns</div>
        </div>
        <div class="formula-row">
          <div class="fname">Forecasted Demand (check value)</div>
          <div class="fexpr">Forecast = AvgDailyDemand × 30</div>
        </div>
      </div>
      <div class="disclaimer">
        <strong>Disclaimers:</strong> Z (the service-level factor) is looked up by ABC class only — 2.05 / 1.64 / 1.28 for A / B / C (98% / 95% / 90% service level) — not by XYZ class; a part can be volatile and still low-value. A Lead Time of 0 days means Epicor has no lead time on file for that part, not that it ships same-day — Site Minimum, EOQ, and Site Maximum are understated until it's corrected (see the warning above and "Save Correction"). These formulas assume independent, roughly normal demand; thin-tailed or lumpy demand (common in Z-class parts) will understate the true minimum. This calculator is a sanity check for buyers, not a replacement for the pipeline — don't hand-key its output into Epicor.
      </div>
    </div>
  </section>

  <!-- ============ ABC/XYZ VIEW ============ -->
  <section class="view" id="view-abc">
    <div class="page-head">
      <h2>ABC / XYZ classification</h2>
      <p>Each cell shows part count and cumulative spend for that segment. Darker shading = higher inventory priority. A = highest spend, X = most predictable demand.</p>
    </div>
    <div class="card">
      <div class="mx-wrap">
        <div class="mx-grid" id="mxgrid"></div>
      </div>
    </div>
    <div class="def-strip">
      <div class="def-item"><b>A / B / C</b>Spend tier — A parts are the top cumulative spend (typically ~80/20 Pareto cut).</div>
      <div class="def-item"><b>X / Y / Z</b>Demand volatility — X is steady and predictable, Z is erratic or intermittent.</div>
      <div class="def-item"><b>Priority reading</b>AX needs the tightest control; CZ is high in count but low enough in spend/predictability to often warrant manual judgment instead of automation.</div>
      <div class="def-item"><b>Cell shading</b>Darker = higher inventory priority, independent of part count.</div>
    </div>
  </section>

  <!-- ============ BROWSE VIEW ============ -->
  <section class="view" id="view-browse">
    <div class="page-head">
      <h2>Browse all parts</h2>
      <p>{N:,} parts from the current pipeline run. Filter by class or policy, or search by part number.</p>
    </div>
    <div class="card">
      <div class="panel-body" style="padding-bottom:0;">
        <!-- Filters -->
        <div class="tbl-filters">
          <div class="flt-group">
            <span class="flt-label">ABC</span>
            <div class="pill-row">{abc_pills}</div>
          </div>
          <div class="flt-group">
            <span class="flt-label">XYZ</span>
            <div class="pill-row">{xyz_pills}</div>
          </div>
          <div class="flt-group">
            <span class="flt-label">Policy</span>
            <div class="pill-row">{policy_pills}</div>
          </div>
          <input class="tbl-search" id="tbl-search" type="text"
            placeholder="Search part number…" oninput="onTblSearch(this.value)">
        </div>
        <!-- Filter status -->
        <div class="fbar">
          Showing <strong id="showing">{N:,}</strong> of <strong>{N:,}</strong> parts
          <span id="atags"></span>
        </div>
      </div>
      <!-- Table -->
      <div class="tbl-wrap">
        <table><thead id="thead"></thead><tbody id="tbody"></tbody></table>
      </div>
      <div class="panel-body" style="padding-top:0;">
        <div class="tbl-foot">
          <span id="tbl-range" style="color:var(--tlt)"></span>
          <div style="display:flex;align-items:center;gap:14px">
            <span id="tbl-cnt" style="color:var(--tlt)"></span>
            <div class="pgn" id="pgn"></div>
          </div>
        </div>
      </div>
    </div>
  </section>

</div><!-- /page -->

<footer class="status">
  Pipeline last refreshed {now} · scripts 03–07 · {N:,} parts loaded
</footer>

<script>{JS}</script>
</body>
</html>"""

    return html


# ── ENTRY POINT ──────────────────────────────────────────
if __name__ == "__main__":
    print("Loading data...")
    df = load_data()
    print(f"  Rows: {len(df):,}")
    print("Building dashboard...")
    html = build_html(df)
    out = "dashboard.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {out}  ({len(html)//1024} KB)")
    webbrowser.open(out)
