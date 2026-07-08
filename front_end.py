# front_end.py — Generates dashboard.html from stocking_model_output.xlsx
# Run: python front_end.py

import pandas as pd
import numpy as np
import json
import webbrowser
from datetime import datetime

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
def load_data():
    df = pd.read_excel("stocking_model_output.xlsx")
    for col in ["ForecastedDemand", "SafetyStock", "ROP", "EOQ"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Pull spend from abc_xyz_matrix.csv for the matrix display
    try:
        mx = pd.read_csv("abc_xyz_matrix.csv")[["PartNum", "TotalSpend"]]
        df = df.merge(mx, on="PartNum", how="left")
    except Exception:
        df["TotalSpend"] = np.nan

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

    # Table data (all cols needed by the lookup and table)
    keep = ["PartNum", "ABC", "XYZ", "ABCXYZ",
            "ForecastedDemand", "SafetyStock", "ROP", "EOQ", "Policy"]
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
  --bg:      #F5EFE6;
  --card:    #FDFAF5;
  --chdr:    #EDE5D8;
  --accent:  #C98B50;
  --accent2: #D4AA72;
  --primary: #7B5B38;
  --text:    #3A2C1E;
  --tmid:    #6B5240;
  --tlt:     #9B8070;
  --brd:     #DDD0C0;
  --brdl:    #EDE5D8;
  --topbar:  #2E2218;
  --sh:      0 2px 8px rgba(58,44,30,.10);
  --sh-md:   0 4px 16px rgba(58,44,30,.14);
}
*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
body {
  font-family:"Segoe UI", system-ui, sans-serif;
  background:var(--bg); color:var(--text);
  min-height:100vh; overflow-y:auto;
}

/* TOPBAR */
.topbar {
  background:var(--topbar); color:#F0E4D0;
  display:flex; align-items:center; justify-content:space-between;
  padding:0 32px; height:52px;
  border-bottom:3px solid var(--accent); position:sticky; top:0; z-index:20;
}
.tb-left { display:flex; align-items:center; gap:14px; }
.tb-logo { background:var(--accent); color:#fff; font-weight:700; font-size:12px; padding:4px 9px; border-radius:4px; }
.tb-title { font-size:16px; font-weight:600; }
.tb-right { font-size:11px; color:var(--accent2); text-align:right; }

/* PAGE */
.page { max-width:1060px; margin:0 auto; padding:28px 24px 48px; display:flex; flex-direction:column; gap:28px; }

/* SECTION LABEL */
.sec-label {
  font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:1px; color:var(--tlt); margin-bottom:8px;
}

/* CARD */
.card {
  background:var(--card); border-radius:10px;
  border:1px solid var(--brdl); box-shadow:var(--sh);
}
.card-hdr {
  padding:12px 18px; background:var(--chdr);
  border-bottom:1px solid var(--brdl);
  font-size:13px; font-weight:600; color:var(--text);
}

/* ── MATRIX ─────────────────────────────────── */
.mx-wrap { padding:14px; }
.mx-grid {
  display:grid;
  grid-template-columns:30px repeat(3,1fr);
  gap:5px;
}
.mx-hdr-cell {
  background:transparent; color:var(--tlt);
  font-size:9.5px; font-weight:700; text-transform:uppercase;
  letter-spacing:.7px; padding:4px 0; text-align:center;
}
.mx-side-cell {
  writing-mode:vertical-rl; text-orientation:mixed; transform:rotate(180deg);
  font-size:9.5px; color:var(--tlt); font-weight:700; text-transform:uppercase;
  text-align:center; padding:4px 0;
}
.mx-data-cell {
  border-radius:8px; padding:12px 10px;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  text-align:center; min-height:74px;
  transition:transform .1s;
}
.mx-data-cell:hover { transform:scale(1.02); }
.cx-key   { font-size:10px; font-weight:700; margin-bottom:4px; opacity:.8; }
.cx-count { font-size:22px; font-weight:700; line-height:1; }
.cx-spend { font-size:10px; margin-top:3px; opacity:.75; }
/* Cell colors — darkest = highest priority */
.cAX { background:#3D2008; color:#fff; }
.cAY { background:#5A3010; color:#fff; }
.cAZ { background:#7A4A20; color:#fff; }
.cBX { background:#C98B50; color:#fff; }
.cBY { background:#D4A06B; color:#3A2C1E; }
.cBZ { background:#DEB882; color:#3A2C1E; }
.cCX { background:#E8CFA8; color:#5A4030; }
.cCY { background:#EDD8B4; color:#6B5240; }
.cCZ { background:#F2E4C8; color:#8B7060; }
.cempty { background:var(--brdl); color:var(--tlt); }

/* ── PART LOOKUP ────────────────────────────── */
.lookup-body { padding:18px; display:flex; flex-direction:column; gap:14px; }
.lookup-input-row { display:flex; gap:10px; align-items:center; }
.lookup-input {
  flex:1; padding:10px 14px; border-radius:7px;
  border:2px solid var(--brd); background:#fff;
  font-size:14px; color:var(--text); outline:none;
  transition:border-color .15s;
}
.lookup-input:focus { border-color:var(--accent); }
.lookup-clear {
  padding:9px 14px; border-radius:7px;
  border:1px solid var(--brd); background:transparent;
  color:var(--tmid); font-size:12px; cursor:pointer;
  transition:all .15s; white-space:nowrap;
}
.lookup-clear:hover { border-color:var(--accent); color:var(--accent); }

/* Result card */
.result-card {
  display:none; border-radius:8px;
  border:2px solid var(--accent); overflow:hidden;
}
.result-card.visible { display:block; }
.result-header {
  background:var(--accent); color:#fff;
  padding:10px 16px; display:flex; align-items:center;
  justify-content:space-between;
}
.result-partnum { font-size:15px; font-weight:700; }
.result-class-badge {
  background:rgba(255,255,255,.22); color:#fff;
  padding:3px 10px; border-radius:12px;
  font-size:12px; font-weight:700;
}
.result-rows { padding:0; }
.result-row {
  display:flex; align-items:center;
  padding:10px 16px; border-bottom:1px solid var(--brdl);
}
.result-row:last-child { border-bottom:none; }
.result-row:nth-child(even) { background:#FAF5EE; }
.result-lbl {
  width:220px; font-size:12px; font-weight:600;
  color:var(--tmid); flex-shrink:0;
}
.result-val { font-size:14px; font-weight:600; color:var(--text); }
.result-unit { font-size:11px; color:var(--tlt); margin-left:5px; font-weight:400; }
.result-policy-badge {
  display:inline-block; padding:3px 10px;
  border-radius:12px; font-size:11px; font-weight:700;
}
.badge-auto     { background:#3D2008; color:#fff; }
.badge-periodic { background:#C98B50; color:#fff; }
.badge-manual   { background:#E8CFA8; color:#5A4030; }
.no-result {
  display:none; padding:14px 16px;
  color:var(--tlt); font-size:13px; font-style:italic;
}
.no-result.visible { display:block; }

/* ── MODE TOGGLE ────────────────────────────── */
.mode-toggle { display:flex; gap:6px; }
.mode-btn {
  padding:5px 14px; border-radius:7px;
  border:1px solid var(--brd); background:transparent;
  color:var(--tmid); font-size:12px; font-weight:600; cursor:pointer;
  transition:all .15s;
}
.mode-btn:hover { border-color:var(--accent); color:var(--accent); }
.mode-btn.active { background:var(--accent); border-color:var(--accent); color:#fff; }

/* ── CALCULATOR MODE ────────────────────────── */
.calc-body { display:none; padding:18px; flex-direction:column; gap:16px; }
.calc-body.visible { display:flex; }
.calc-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
@media (max-width:760px) { .calc-grid { grid-template-columns:repeat(2,1fr); } }
.calc-field label {
  font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
  color:var(--tlt); display:block; margin-bottom:4px;
}
.calc-field input, .calc-field select {
  width:100%; padding:8px 10px; border-radius:6px;
  border:1px solid var(--brd); background:#fff; font-size:13px; color:var(--text);
}
.calc-field input:focus, .calc-field select:focus { outline:none; border-color:var(--accent); }
.calc-results { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
@media (max-width:760px) { .calc-results { grid-template-columns:repeat(2,1fr); } }
.calc-card { background:var(--chdr); border-radius:8px; padding:11px 12px; }
.calc-card .cc-lbl {
  font-size:9.5px; font-weight:700; text-transform:uppercase;
  letter-spacing:.5px; color:var(--tlt); margin-bottom:4px;
}
.calc-card .cc-val { font-size:17px; font-weight:700; color:var(--primary); }
.calc-card .cc-unit { font-size:10px; color:var(--tlt); font-weight:400; margin-left:3px; }
.calc-policy {
  display:inline-block; padding:3px 10px; border-radius:12px;
  font-size:11px; font-weight:700; background:var(--accent); color:#fff;
}
.calc-xyz-select {
  margin-left:8px; width:auto; display:inline-block;
  padding:4px 8px; border-radius:6px; border:1px solid var(--brd); font-size:11px;
}
.compare-toggle {
  display:flex; align-items:center; gap:6px; cursor:pointer;
  font-size:12px; font-weight:600; color:var(--primary); user-select:none;
}
.compare-body { display:none; margin-top:10px; }
.compare-body.open { display:block; }
.delta-row {
  display:grid; grid-template-columns:1.3fr 1fr 1fr .8fr;
  gap:8px; align-items:center; font-size:12px;
  padding:7px 0; border-bottom:1px solid var(--brdl);
}
.delta-row:last-child { border-bottom:none; }
.flag { font-size:10.5px; font-weight:700; padding:2px 7px; border-radius:6px; text-align:center; }
.flag-good { background:#E3EFD3; color:#3B6D11; }
.flag-warn { background:#F6E6C8; color:#854F0B; }
.flag-bad  { background:#F6D8D2; color:#A32D2D; }
.calc-actions { display:flex; gap:10px; flex-wrap:wrap; }
.calc-btn { padding:9px 16px; border-radius:7px; border:none; font-size:12.5px; font-weight:600; cursor:pointer; }
.calc-btn-primary { background:var(--primary); color:#fff; }
.calc-btn-primary:hover { opacity:.9; }
.calc-btn-secondary { background:var(--chdr); color:var(--primary); }
.calc-btn-secondary:hover { background:var(--brd); }
.calc-log-empty { font-size:12px; color:var(--tlt); padding:8px 0; }
.calc-note { font-size:11px; color:var(--tlt); margin-top:2px; }
.calc-section-lbl {
  font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:.7px; color:var(--tlt); margin-top:4px;
}
.calc-log-table { width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }
.calc-log-table th {
  text-align:left; padding:6px 8px; font-size:10px; font-weight:700;
  text-transform:uppercase; color:var(--tmid); border-bottom:2px solid var(--brd);
}
.calc-log-table td { padding:6px 8px; border-bottom:1px solid var(--brdl); }
.calc-del-btn {
  padding:3px 8px; border-radius:5px; border:1px solid var(--brd);
  background:var(--bg); color:var(--tmid); font-size:11px; cursor:pointer;
}
.calc-del-btn:hover { border-color:var(--accent); color:var(--accent); }

/* ── TABLE SECTION ──────────────────────────── */
.tbl-filters {
  display:flex; flex-wrap:wrap; gap:12px;
  align-items:center; padding:12px 18px;
  background:var(--chdr); border-bottom:1px solid var(--brdl);
}
.flt-group { display:flex; align-items:center; gap:6px; }
.flt-label {
  font-size:9.5px; font-weight:700; text-transform:uppercase;
  letter-spacing:.7px; color:var(--tlt); white-space:nowrap;
}
.pill-row { display:flex; gap:4px; flex-wrap:wrap; }
.pill {
  padding:3px 9px; border-radius:11px;
  border:1px solid var(--brd); background:transparent;
  color:var(--tmid); font-size:11px; cursor:pointer; transition:all .15s;
}
.pill:hover  { border-color:var(--accent); color:var(--accent); }
.pill.active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.tbl-search {
  margin-left:auto; padding:6px 10px; border-radius:6px;
  border:1px solid var(--brd); background:#fff;
  font-size:12px; outline:none; width:180px;
}
.tbl-search:focus { border-color:var(--accent); }

.fbar {
  padding:7px 18px; font-size:11.5px; color:var(--tmid);
  border-bottom:1px solid var(--brdl); background:var(--card);
  display:flex; align-items:center; gap:8px; flex-wrap:wrap;
}
.fbar strong { color:var(--primary); }
.ftag {
  background:var(--accent); color:#fff;
  padding:1px 7px; border-radius:9px; font-size:10.5px; font-weight:600;
}

.tbl-wrap { overflow-x:auto; max-height:400px; overflow-y:auto; }
.tbl-wrap::-webkit-scrollbar { height:4px; width:4px; }
.tbl-wrap::-webkit-scrollbar-thumb { background:var(--brd); }
table { width:100%; border-collapse:collapse; font-size:12px; }
thead th {
  position:sticky; top:0; z-index:2;
  background:var(--chdr); padding:9px 13px;
  text-align:left; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.5px; color:var(--tmid);
  border-bottom:2px solid var(--brd); cursor:pointer; white-space:nowrap;
  user-select:none;
}
thead th:hover { color:var(--accent); }
.si { font-size:9px; margin-left:2px; color:var(--tlt); }
tbody tr { border-bottom:1px solid var(--brdl); transition:background .1s; cursor:pointer; }
tbody tr:hover { background:#F2E8DA; }
tbody td { padding:8px 13px; white-space:nowrap; }
.badge-cls {
  display:inline-block; padding:2px 8px; border-radius:10px;
  font-size:10px; font-weight:700; text-transform:uppercase;
}
.bc-A { background:#3D2008; color:#fff; }
.bc-B { background:#C98B50; color:#fff; }
.bc-C { background:#E8CFA8; color:#5A4030; }
.tbl-foot {
  padding:9px 18px; display:flex; align-items:center;
  justify-content:space-between; border-top:1px solid var(--brdl);
  font-size:12px; color:var(--tmid);
}
.pgn { display:flex; gap:5px; align-items:center; }
.pbtn {
  padding:3px 9px; border-radius:5px;
  border:1px solid var(--brd); background:var(--bg);
  color:var(--tmid); font-size:12px; cursor:pointer;
}
.pbtn:hover  { border-color:var(--accent); color:var(--accent); }
.pbtn.active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.pbtn:disabled { opacity:.4; cursor:default; }
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

function showResult(p) {{
  document.getElementById("res-partnum").textContent = p.PartNum || "—";
  document.getElementById("res-class").textContent   = p.ABCXYZ  || "—";

  const fmtN = v => v != null ? Number(v).toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:2}}) : "—";
  document.getElementById("res-fd").textContent  = fmtN(p.ForecastedDemand);
  document.getElementById("res-ss").textContent  = fmtN(p.SafetyStock);
  document.getElementById("res-rop").textContent = fmtN(p.ROP);
  document.getElementById("res-eoq").textContent = fmtN(p.EOQ);

  const pol = p.Policy || "—";
  const lc  = pol.toLowerCase();
  const cls = lc.includes("automated") ? "auto" : lc.includes("periodic") ? "periodic" : "manual";
  const polEl = document.getElementById("res-policy");
  polEl.textContent  = pol;
  polEl.className    = `result-policy-badge badge-${{cls}}`;

  // Header color by ABC
  const hdr = document.getElementById("result-header");
  const abc = (p.ABC||"").toUpperCase();
  hdr.style.background = abc==="A" ? "#3D2008" : abc==="B" ? "#C98B50" : "#A0743E";
}}

function clearLookup() {{
  document.getElementById("lookup-input").value = "";
  document.getElementById("lookup-result").classList.remove("visible");
  document.getElementById("no-result").classList.remove("visible");
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
  {{ key:"SafetyStock",      label:"Safety Stock",    w:"110px", num:true }},
  {{ key:"ROP",              label:"ROP",             w:"90px",  num:true }},
  {{ key:"EOQ",              label:"EOQ",             w:"90px",  num:true }},
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
const Z_LOOKUP = { "1.28":0.90, "1.65":0.95, "2.05":0.98, "2.33":0.99 };
const STORAGE_AVAILABLE = typeof window.storage !== "undefined";
let memoryCalcLog = [];

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
  if (["AX","AY","BX","BY"].includes(code)) return "Automated reorder candidate";
  if (["AZ","BZ"].includes(code)) return "Periodic review recommended";
  return "Not modeled (C-tier)";
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
  const z = parseFloat(document.getElementById("c-service").value);

  const forecastMonthly = avgDaily * 30;
  const safetyStock = z * Math.sqrt(leadTime) * stdDaily;
  const rop = (avgDaily * leadTime) + safetyStock;
  const annualDemand = avgDaily * 365;
  const holdingCostPerUnit = (holdRatePct / 100) * unitCost;
  const eoq = holdingCostPerUnit > 0 && annualDemand > 0
    ? Math.sqrt((2 * annualDemand * orderCost) / holdingCostPerUnit)
    : 0;

  document.getElementById("c-out-fd").textContent  = forecastMonthly.toFixed(2);
  document.getElementById("c-out-ss").textContent  = safetyStock.toFixed(2);
  document.getElementById("c-out-rop").textContent = rop.toFixed(2);
  document.getElementById("c-out-eoq").textContent = eoq.toFixed(2);

  const abc = document.getElementById("c-abc").value;
  const xyz = document.getElementById("c-xyz").value;
  document.getElementById("c-out-policy").textContent = calcPolicyFor(abc, xyz);

  const calc = { forecastMonthly, safetyStock, rop, eoq };
  renderCalcDeltas(calc);
  return calc;
}

function renderCalcDeltas(calc) {
  const rows = [
    ["Forecasted demand", calc.forecastMonthly, document.getElementById("c-pfd").value],
    ["Safety stock",      calc.safetyStock,      document.getElementById("c-pss").value],
    ["Reorder point",     calc.rop,              document.getElementById("c-prop").value],
    ["EOQ",               calc.eoq,              document.getElementById("c-peoq").value],
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

function calcAutofillFromPart(val) {
  const q = (val||"").trim().toLowerCase();
  if (!q) return;
  const part = ALL_DATA.find(d => (d.PartNum||"").toLowerCase() === q);
  if (!part) return;
  document.getElementById("c-abc").value = part.ABC || "";
  document.getElementById("c-xyz").value = part.XYZ || "";
  document.getElementById("c-pfd").value  = part.ForecastedDemand ?? "";
  document.getElementById("c-pss").value  = part.SafetyStock ?? "";
  document.getElementById("c-prop").value = part.ROP ?? "";
  document.getElementById("c-peoq").value = part.EOQ ?? "";
  const body = document.getElementById("compare-body");
  if (!body.classList.contains("open")) toggleCompare();
  calcCompute();
}

["c-service","c-avgdaily","c-stddaily","c-leadtime","c-unitcost","c-ordercost","c-holdrate",
 "c-abc","c-xyz","c-pfd","c-pss","c-prop","c-peoq"]
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
  if (entry.pipeline.fd  !== "") flags.push(calcDeltaFlag(entry.calc.forecastMonthly, parseFloat(entry.pipeline.fd)  || 0));
  if (entry.pipeline.ss  !== "") flags.push(calcDeltaFlag(entry.calc.safetyStock,     parseFloat(entry.pipeline.ss)  || 0));
  if (entry.pipeline.rop !== "") flags.push(calcDeltaFlag(entry.calc.rop,             parseFloat(entry.pipeline.rop) || 0));
  if (entry.pipeline.eoq !== "") flags.push(calcDeltaFlag(entry.calc.eoq,             parseFloat(entry.pipeline.eoq) || 0));
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
      <td>${entry.calc.safetyStock.toFixed(2)}</td>
      <td>${entry.calc.rop.toFixed(2)}</td>
      <td>${entry.calc.eoq.toFixed(2)}</td>
      <td>${flag ? `<span class="flag ${flag.cls}">${flag.label}</span>` : "—"}</td>
      <td><button class="calc-del-btn" onclick="deleteCalcEntry(${entry.savedAt})">Delete</button></td>
    </tr>`;
  }).join("");
  container.innerHTML = `<table class="calc-log-table">
    <thead><tr><th>Part #</th><th>Saved</th><th>Forecast</th><th>Safety</th><th>ROP</th><th>EOQ</th><th>Check</th><th></th></tr></thead>
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
      fd:  document.getElementById("c-pfd").value,
      ss:  document.getElementById("c-pss").value,
      rop: document.getElementById("c-prop").value,
      eoq: document.getElementById("c-peoq").value
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
    calc.safetyStock.toFixed(2),
    calc.rop.toFixed(2),
    calc.eoq.toFixed(2),
    calcPolicyFor(abc, xyz)
  ].join("\\t");
  navigator.clipboard.writeText(row).catch(() => {});
}

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
  <style>{CSS}</style>
</head>
<body>

<!-- TOPBAR -->
<header class="topbar">
  <div class="tb-left">
    <div class="tb-logo">ETNYRE</div>
    <div>
      <div class="tb-title">Stocking Model</div>
    </div>
  </div>
  <div class="tb-right">
    <div>{N:,} parts &nbsp;·&nbsp; Generated {now}</div>
  </div>
</header>

<div class="page">

  <!-- 1. ABC/XYZ MATRIX -->
  <div>
    <div class="sec-label">ABC / XYZ Classification</div>
    <div class="card">
      <div class="mx-wrap">
        <div class="mx-grid" id="mxgrid"></div>
        <div style="margin-top:10px;font-size:10px;color:var(--tlt);">
          Each cell shows part count and cumulative spend &nbsp;·&nbsp; Darker = higher inventory priority
        </div>
      </div>
    </div>
  </div>

  <!-- 2. PART LOOKUP -->
  <div>
    <div class="sec-label">Part Lookup</div>
    <div class="card">
      <div class="card-hdr" style="display:flex;align-items:center;justify-content:space-between;">
        <span>Enter a Part Number</span>
        <div class="mode-toggle">
          <button class="mode-btn active" id="mode-btn-lookup" onclick="setMode('lookup')">Lookup</button>
          <button class="mode-btn" id="mode-btn-calc" onclick="setMode('calc')">Calculator</button>
        </div>
      </div>
      <div class="lookup-body" id="lookup-panel">
        <div class="lookup-input-row">
          <input class="lookup-input" id="lookup-input" type="text"
            list="part-list" placeholder="Type or paste a part number…"
            oninput="lookupPart(this.value)" autocomplete="off">
          <datalist id="part-list"></datalist>
          <button class="lookup-clear" onclick="clearLookup()">✕ Clear</button>
        </div>

        <div class="no-result" id="no-result">No part found with that number.</div>

        <div class="result-card" id="lookup-result">
          <div class="result-header" id="result-header">
            <span class="result-partnum" id="res-partnum"></span>
            <span class="result-class-badge" id="res-class"></span>
          </div>
          <div class="result-rows">
            <div class="result-row">
              <div class="result-lbl">Forecasted Demand</div>
              <div class="result-val"><span id="res-fd"></span><span class="result-unit">units / month</span></div>
            </div>
            <div class="result-row">
              <div class="result-lbl">Safety Stock</div>
              <div class="result-val"><span id="res-ss"></span><span class="result-unit">units</span></div>
            </div>
            <div class="result-row">
              <div class="result-lbl">Reorder Point (ROP)</div>
              <div class="result-val"><span id="res-rop"></span><span class="result-unit">units</span></div>
            </div>
            <div class="result-row">
              <div class="result-lbl">Eco. Order Qty (EOQ)</div>
              <div class="result-val"><span id="res-eoq"></span><span class="result-unit">units per order</span></div>
            </div>
            <div class="result-row">
              <div class="result-lbl">Policy</div>
              <div class="result-val"><span id="res-policy" class="result-policy-badge"></span></div>
            </div>
          </div>
        </div>

      </div>

      <!-- CALCULATOR MODE -->
      <div class="calc-body" id="calc-panel">
        <div class="calc-grid">
          <div class="calc-field">
            <label for="c-partnum">Part number (optional — autofills pipeline values below if it matches)</label>
            <input type="text" id="c-partnum" list="part-list" placeholder="e.g. 6605173" oninput="calcAutofillFromPart(this.value)" autocomplete="off">
          </div>
          <div class="calc-field">
            <label for="c-service">Service level</label>
            <select id="c-service">
              <option value="1.28">90%</option>
              <option value="1.65" selected>95%</option>
              <option value="2.05">98%</option>
              <option value="2.33">99%</option>
            </select>
          </div>
          <div class="calc-field">
            <label for="c-abc">ABC class (optional)</label>
            <select id="c-abc">
              <option value="">—</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
            </select>
          </div>
          <div class="calc-field">
            <label for="c-avgdaily">Avg daily demand (units/day)</label>
            <input type="number" id="c-avgdaily" step="any" value="0.5">
          </div>
          <div class="calc-field">
            <label for="c-stddaily">Std dev of daily demand (units/day)</label>
            <input type="number" id="c-stddaily" step="any" value="0.3">
          </div>
          <div class="calc-field">
            <label for="c-leadtime">Lead time (days)</label>
            <input type="number" id="c-leadtime" step="any" value="30">
          </div>
          <div class="calc-field">
            <label for="c-unitcost">Unit cost ($)</label>
            <input type="number" id="c-unitcost" step="any" value="120">
          </div>
          <div class="calc-field">
            <label for="c-ordercost">Ordering cost per PO ($)</label>
            <input type="number" id="c-ordercost" step="any" value="50">
          </div>
          <div class="calc-field">
            <label for="c-holdrate">Holding cost rate (% of unit cost / year)</label>
            <input type="number" id="c-holdrate" step="any" value="25">
          </div>
        </div>

        <div class="calc-results">
          <div class="calc-card">
            <div class="cc-lbl">Forecasted demand</div>
            <div class="cc-val" id="c-out-fd">—</div><span class="cc-unit">units/mo</span>
          </div>
          <div class="calc-card">
            <div class="cc-lbl">Safety stock</div>
            <div class="cc-val" id="c-out-ss">—</div><span class="cc-unit">units</span>
          </div>
          <div class="calc-card">
            <div class="cc-lbl">Reorder point</div>
            <div class="cc-val" id="c-out-rop">—</div><span class="cc-unit">units</span>
          </div>
          <div class="calc-card">
            <div class="cc-lbl">EOQ</div>
            <div class="cc-val" id="c-out-eoq">—</div><span class="cc-unit">units/order</span>
          </div>
        </div>

        <div>
          <span class="calc-policy" id="c-out-policy">Select ABC + XYZ</span>
          <select id="c-xyz" class="calc-xyz-select">
            <option value="">XYZ —</option><option value="X">X</option><option value="Y">Y</option><option value="Z">Z</option>
          </select>
        </div>
        <p class="calc-note">Forecasted demand here is a simple avg daily demand × 30 — a check value, not the moving-average/Holt-Winters model the pipeline uses. A large gap from the pipeline's number is itself a useful signal.</p>

        <div>
          <div class="compare-toggle" id="compare-toggle" onclick="toggleCompare()">
            <span id="compare-arrow">▸</span> Compare against pipeline values for this part
          </div>
          <div class="compare-body" id="compare-body">
            <div class="calc-grid" style="margin-top:10px;">
              <div class="calc-field"><label for="c-pfd">Pipeline forecast</label><input type="number" id="c-pfd" step="any" placeholder="from dashboard"></div>
              <div class="calc-field"><label for="c-pss">Pipeline safety stock</label><input type="number" id="c-pss" step="any" placeholder="from dashboard"></div>
              <div class="calc-field"><label for="c-prop">Pipeline ROP</label><input type="number" id="c-prop" step="any" placeholder="from dashboard"></div>
              <div class="calc-field"><label for="c-peoq">Pipeline EOQ</label><input type="number" id="c-peoq" step="any" placeholder="from dashboard"></div>
            </div>
            <div id="delta-table" style="margin-top:8px;"></div>
            <p class="calc-note">Green = within 5%. Amber = 5–20% off. Red = more than 20% off — usually means the demand input feeding the pipeline differs from what's entered here.</p>
          </div>
        </div>

        <div class="calc-actions">
          <button class="calc-btn calc-btn-primary" onclick="saveCalcCheck()">Save this check</button>
          <button class="calc-btn calc-btn-secondary" onclick="copyCalcRow()">Copy row for Excel</button>
        </div>

        <div>
          <div class="calc-section-lbl">Saved checks</div>
          <div id="calc-log"><div class="calc-log-empty">No checks saved yet.</div></div>
        </div>
      </div>

    </div>
  </div>

  <!-- 3. BROWSE TABLE -->
  <div>
    <div class="sec-label">Browse All Parts</div>
    <div class="card">
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
      <!-- Table -->
      <div class="tbl-wrap">
        <table><thead id="thead"></thead><tbody id="tbody"></tbody></table>
      </div>
      <div class="tbl-foot">
        <span id="tbl-range" style="color:var(--tlt)"></span>
        <div style="display:flex;align-items:center;gap:14px">
          <span id="tbl-cnt" style="color:var(--tlt)"></span>
          <div class="pgn" id="pgn"></div>
        </div>
      </div>
    </div>
  </div>

</div><!-- /page -->

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
