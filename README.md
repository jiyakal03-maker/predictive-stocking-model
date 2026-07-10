# Stocking Model

A predictive inventory stocking pipeline for Etnyre International Ltd, built to sit alongside normal purchasing workflows — not replace them. It turns raw Epicor Kinetic PO history into buyer-facing recommendations: how to classify a part, how much safety stock to hold, when to reorder, and how much to order.

The output is meant to be read by buyers, not just data people. Every number the pipeline produces should be traceable back to a formula a non-technical stakeholder can look up and sanity-check — that's the design principle behind both this pipeline and the Part Lookup dashboard that sits on top of it.

---

## Pipeline overview

```
spend_clean.csv (raw Epicor PO history, ~57K rows / ~16K parts)
        │
        ▼
01_xxx.py / 02_xxx.py   →  cleaning, ABC/XYZ classification
        │
        ▼
03_safety_stock.py      →  Site Minimum (safety stock)
        │
        ▼
04_ROP.py                →  reorder point logic (built on Site Min)
        │
        ▼
05_demand_forecast.py   →  Holt-Winters demand forecast
        │
        ▼
06_EOQ.py                →  Economic Order Quantity, Site Maximum
        │
        ▼
07_consolidate.py       →  joins everything, assigns Policy label
        │
        ▼
stocking_model_output.xlsx   (buyer-facing final output)
        │
        ▼
Part Lookup HTML dashboard   (ALL_DATA embed + Lookup/Calculator UI)
```

Each script reads the previous script's CSV output and writes its own — nothing is recomputed silently inside another script. That makes every intermediate number auditable: if a buyer questions a value, you can trace it to the exact CSV and formula that produced it, rather than re-deriving it from scratch.

---

## Script-by-script

### `01` / `02` — Data cleaning & ABC/XYZ classification

Raw Epicor PO history is cleaned into `spend_clean.csv`, then every part is scored on two independent axes:

**ABC (spend tier)** — a Pareto/80-20 cut on cumulative annual spend.
- **A** = highest cumulative spend (roughly the top ~80% of dollars)
- **B** = next tier
- **C** = long tail — thousands of parts, small individual spend

**XYZ (demand volatility)** — based on the coefficient of variation (CV = σ ÷ mean) of each part's demand:
- **X** = stable, predictable demand (low CV)
- **Y** = moderate variability
- **Z** = volatile or intermittent demand (high CV, often near-zero many periods)

These combine into 9 cells (AX, AY, AZ, BX, BY, BZ, CX, CY, CZ), each carrying a different inventory priority — this is the matrix shown on the dashboard's ABC/XYZ Overview tab.

**A known demand-aggregation bug was found and fixed here**: zero-demand days were being excluded from the daily demand calculation, which artificially inflated the mean and understated true variability — cascading into inflated Site Minimum and ROP values downstream. The fix reindexes every part across the full dataset's date range using `pd.date_range()`, so days with genuinely zero demand are counted as zero, not dropped.

### `03_safety_stock.py` — Site Minimum

Computes the buffer stock held to protect against demand variation during lead time:

```
Site Minimum = ROUNDUP(Z × σ × √LT, 0)
```

| Symbol | Meaning |
|---|---|
| `Z` | Service-level factor, driven by XYZ class (see table below) |
| `σ` | Standard deviation of daily demand |
| `LT` | Lead time, in days |

Service level is tied to **XYZ class, not ABC class** — a part can be high-spend (A) and still low-volatility (X); the buffer size depends on how unpredictable demand is, not how expensive the part is.

| Class | Z | Service level |
|---|---|---|
| X | ~1.28–1.65 | 90–95% |
| Y | ~1.65 | 95% |
| Z | ~2.05 | 98% |

Note this formula has **no demand term** — it depends only on variability and lead time. That's intentional: it's a pure buffer-against-uncertainty calculation, separate from the baseline reorder trigger.

### `04_ROP.py` — Reorder point

Built on top of Site Minimum. (Earlier versions of this script used a legacy ROP formula that included an average-demand term; that was replaced to match Site Minimum exactly, and the column was renamed from "ROP" to "Site Minimum" everywhere it surfaces to buyers — the filename stayed `04_ROP.py` for continuity with the rest of the pipeline.)

### `05_demand_forecast.py` — Holt-Winters demand forecasting

This is the model the *pipeline* actually orders against — distinct from the simple average shown as a "check value" on the dashboard's calculator.

**Why Holt-Winters, and not a flat average?**
A flat average (total demand ÷ number of periods) treats every part as if demand is constant over time. Most parts aren't — demand drifts up or down (trend) and some parts have recurring seasonal patterns (e.g. tied to production schedules). Holt-Winters (triple exponential smoothing) explicitly models three components instead of collapsing everything into one number:

```
Level (l_t)     — the current baseline value, smoothed
Trend (b_t)     — the current direction/rate of change
Seasonal (s_t)  — the repeating pattern layered on top of level + trend
```

Each component is updated every period using a smoothing weight between 0 and 1:

```
Level:     l_t = α(y_t / s_(t-m)) + (1-α)(l_(t-1) + b_(t-1))
Trend:     b_t = β(l_t - l_(t-1)) + (1-β)b_(t-1)
Seasonal:  s_t = γ(y_t / l_t) + (1-γ)s_(t-m)

Forecast:  ŷ_(t+h) = (l_t + h·b_t) × s_(t+h-m)
```

- **α (alpha)** — how much weight recent actuals get vs. the smoothed history, for the level
- **β (beta)** — how quickly the trend estimate reacts to change
- **γ (gamma)** — how quickly the seasonal pattern is allowed to shift
- **m** — the length of one seasonal cycle

Higher values of α/β/γ make the model react faster to recent changes (more responsive, more noise-sensitive); lower values smooth harder (more stable, slower to catch real shifts). The pipeline fits these per part rather than using one global setting, since a CX part's demand pattern looks nothing like an AZ part's.

**Fallback logic:** parts without enough history for a reliable trend/seasonal fit fall back to simpler smoothing (moving average or basic exponential smoothing) rather than forcing a Holt-Winters fit on too little data — a model with insufficient history to estimate trend and seasonality will overfit noise.

**This is also why the dashboard's calculator forecast (`AvgDailyDemand × 30`) won't match the pipeline number, and shouldn't.** The calculator is a fast, transparent check — anyone can verify it by hand. Holt-Winters is doing more work: it's trying to separate real trend/seasonality from noise. A gap between the two isn't automatically an error; it's most informative on Y/Z-class parts where volatility is high enough that a flat average and a smoothed/trended forecast can legitimately diverge by 30–50%+. Large gaps are worth a buyer's attention, but they should be read as "the model sees something the simple check doesn't" first, and investigated as a possible data bug second.

### `06_EOQ.py` — Economic Order Quantity & Site Maximum

**EOQ** — the order quantity that minimizes the combined cost of ordering (fixed cost per PO) and holding (storage/capital cost as a % of unit value):

```
EOQ = ROUNDUP(√(2 × FixedPOCost × AnnualDemand ÷ (HoldingCost% × AccountingValue)), 0)
```

EOQ scales with the **square root** of annual demand — a useful mental model when debugging: if annual demand is off by X%, expect EOQ to be off by roughly √X%, not X%. A forecast discrepancy will always show up smaller, proportionally, in EOQ than it does in the forecast itself.

**Site Maximum** — the ceiling stock level, branching on whether EOQ fits within realistic demand:

```
Site Maximum = EOQ + Site Minimum − 1,  if EOQ ≤ Annual Demand
             = (Avg Daily Demand × Working Days) ÷ Desired Turns,  otherwise
```

The second branch exists for low-demand parts where a straight EOQ + Site Min sum would produce an unrealistically high ceiling relative to how often the part actually turns over.

### `07_consolidate.py` — Final join & Policy label

Left-joins all five intermediate CSVs (`abc_xyz_matrix.csv`, `safety_stock_output.csv`, `rop_output.csv`, `forecast_output.csv`, `eoq_output.csv`) onto the ABC/XYZ matrix by `PartNum`, confirms zero nulls across the joined set, and assigns a buyer-facing policy:

| ABC × XYZ | Policy |
|---|---|
| AX, AY, BX, BY, CX, CY | Automated reorder candidate |
| AZ, BZ | Periodic review recommended |
| CZ | Order-only candidate (manual review) |

CZ parts — high count, low spend, high volatility — are intentionally routed to manual review rather than automation. This lines up with the Phase 5 simulation findings on a 100-part sample: fill rate benchmarks declined sharply from AX down to AZ (93% → 36%), meaning Z-segment parts are where automated formulas are least reliable and buyer judgment adds the most value.

Output: `stocking_model_output.xlsx` — columns `PartNum, ABC, XYZ, ABCXYZ, ForecastedDemand, SafetyStock, ROP, EOQ, Policy`, covering all ~15,992 parts (all nine ABC×XYZ cells, not just A/B).

---

## Disclaimers & known limitations

- **All formulas assume roughly normal, independent demand.** Lumpy or intermittent demand (common in Z-class and many C-class parts) will cause Site Minimum to understate the true buffer needed — this is a known limitation of the safety-stock formula itself, not a bug.
- **Lead time of 0 in the data means Epicor has no lead time on file**, not that the part actually ships instantly. Any part showing 0-day lead time should be treated as understated until confirmed and corrected — see `leadtime_overrides.csv` for the manual-correction workflow.
- **The dashboard's Calculator Mode forecast is a check value, not a pipeline replacement.** It exists so buyers can sanity-check inputs by hand; it is not meant to be hand-keyed back into Epicor.
- **Fill rate is not guaranteed uniformly across classes.** The Phase 5 simulation showed a real accuracy gradient from AX (highest) to AZ (lowest, 36%) — treat automated recommendations on Z-class parts as a starting point for buyer review, not a final answer.

---

## Running the pipeline

```powershell
python 03_safety_stock.py
python 04_ROP.py
python 05_demand_forecast.py
python 06_EOQ.py
python 07_consolidate.py
```

Run in order — each script depends on the previous script's CSV output. Re-run the full sequence (not just the changed script) any time an upstream formula or input file changes, since a fix in an early script won't propagate downstream until everything after it is regenerated.

---

## Data & security

`spend_clean.csv` and all `.xlsx`/`.xls` files are intentionally excluded from version control via `.gitignore` — they contain confidential company pricing and vendor data and should never be committed. If you're setting this up fresh, you'll need your own copy of `spend_clean.csv` sourced from Epicor Kinetic; it isn't included in this repo.

## Requirements

- Python 3.x
- pandas, numpy, statsmodels (Holt-Winters)
- Excel output: openpyxl

---

## Project structure

```
StockingModel/
├── 03_safety_stock.py
├── 04_ROP.py
├── 05_demand_forecast.py
├── 06_EOQ.py
├── 07_consolidate.py
├── leadtime_overrides.csv          # manual lead-time correction workflow
├── stocking_model_output.xlsx      # final buyer-facing output
├── part_lookup_dashboard.html      # buyer-facing lookup/calculator tool
└── spend_clean.csv                 # gitignored — not included
```
