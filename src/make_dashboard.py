"""
Phase 7 (local dashboard) - render a self-contained, INTERACTIVE HTML dashboard.

Turns the reconciliation result into a clean, browser-viewable dashboard
(KPI cards + charts + approvals table) with NO Power BI and NO internet:
everything is inline SVG + CSS + vanilla JS in one .html file you can
double-click.

The row-level fact table is embedded as JSON and every visual is rendered in
the browser, so the built-in slicers (Decision, Cause, Month, Currency, and a
reference search) filter the KPIs, charts and tables live. Bars and donut
segments are also clickable slicers. Nothing is truncated - the approvals
queue shows every filtered human-review break.

Colours use the validated data-viz reference palette; every chart carries
direct labels and a legend so identity never rests on colour alone. Light
and dark mode both ship (prefers-color-scheme).

Run:   python -m src.make_dashboard      (after run.py)
Out:   reports/dashboard.html
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import export_powerbi  # noqa: E402

OUT = config.REPORTS_DIR / "dashboard.html"

# Validated categorical hues (light mode) from the reference palette. Kept in
# sync with the JS PALETTE below so server and client agree on colour->meaning.
CAT = {
    "blue": "#2a78d6", "aqua": "#1baf7a", "yellow": "#eda100",
    "green": "#008300", "orange": "#eb6834", "red": "#e34948",
}
DECISION_HUE = {  # decision -> palette slot (carries meaning, always labelled)
    "MATCHED": "green", "AUTO": "blue", "HUMAN": "orange",
    "NEEDS_REVIEW": "yellow", "QUARANTINE": "red",
}
CAUSE_ORDER = ["amount-mismatch", "missing-in-bank", "missing-in-ledger", "duplicate"]
DECISION_ORDER = ["MATCHED", "AUTO", "HUMAN", "NEEDS_REVIEW", "QUARANTINE"]


# ── glossary (plain-English definitions, straight from the pipeline) ────
def _glossary() -> dict:
    """Definitions built from the live config so thresholds never drift.

    Deliberately separates the reconciliation CAUSE (what the maths found) from
    the AI CATEGORY (what the note says the reason is) - the two overlap on the
    words "duplicate" and "missing", which is the usual source of confusion.
    """
    hv = f"${config.HIGH_VALUE_THRESHOLD:,.0f}"
    lc = f"{config.LOW_CONFIDENCE_THRESHOLD:g}"
    tol = f"${config.AMOUNT_TOLERANCE:g}"
    return {
        "intro": ("Two different columns answer two different questions. "
                  "“Cause” is what the reconciliation maths found by "
                  "comparing amounts; “AI category” is the reason a human "
                  "wrote in the note, read by the AI. The words “duplicate” "
                  "and “missing” can appear in both — one is the "
                  "number, the other is the explanation."),
        "decision": {
            "title": "Decision — who acts on the item",
            "kind": "swatch",
            "rows": [
                ["MATCHED", CAT["green"],
                 "Ledger and bank agree — reconciled automatically, nothing to do."],
                ["AUTO", CAT["blue"],
                 f"Break auto-cleared: the AI note passed validation, value at risk is "
                 f"under {hv}, and confidence is at least {lc}."],
                ["HUMAN", CAT["orange"],
                 f"Sent to a person to approve (maker–checker) because it is "
                 f"high-value (≥ {hv}) or the AI was unsure (confidence < {lc})."],
                ["NEEDS_REVIEW", CAT["yellow"],
                 "A break with no analyst note to classify, so it defaults to human review."],
                ["QUARANTINE", CAT["red"],
                 "The AI output failed validation and is never trusted — held aside "
                 "for inspection."],
            ],
        },
        "cause": {
            "title": "Cause — what the reconciliation maths found",
            "kind": "swatch",
            "rows": [
                ["amount-mismatch", CAT["blue"],
                 f"Both sides have the entry but the amounts differ by more than the "
                 f"{tol} tolerance. Exposure = the difference."],
                ["missing-in-bank", CAT["blue"],
                 "In the ledger but never seen on the bank feed (ledger-only). "
                 "Exposure = the ledger amount."],
                ["missing-in-ledger", CAT["blue"],
                 "On the bank feed but never booked in the ledger (bank-only). "
                 "Exposure = the bank amount."],
                ["duplicate", CAT["blue"],
                 "The same reference booked more than once on the bank side. "
                 "Exposure = the duplicated amount."],
            ],
        },
        "category": {
            "title": "AI category — the reason read from the note",
            "kind": "plain",
            "rows": [
                ["TIMING",
                 "A genuine transaction that simply posts on a different day "
                 "(e.g. settles T+1, value-date difference)."],
                ["DUPLICATE",
                 "The same transaction booked more than once, or a reversal/retry "
                 "(double-booked, re-sent)."],
                ["DATA_ERROR",
                 "A data-entry mistake, usually the wrong amount "
                 "(typo, fat-finger, 9,000 vs 90,000)."],
                ["MISSING",
                 "A real entry present on one side but never booked on the other "
                 "(needs posting)."],
            ],
        },
        "metric": {
            "title": "Key numbers",
            "kind": "plain",
            "rows": [
                ["Value at risk",
                 "The money exposed by a break — what could be wrong or lost if it "
                 "is not resolved."],
                ["Confidence",
                 f"How sure the AI is of its category, 0–1. Below {lc} the item is "
                 f"routed to a human."],
                ["Match rate",
                 "Share of ledger references that reconciled cleanly against the bank "
                 "feed."],
            ],
        },
    }


# ── data payload ───────────────────────────────────────────────────────
def _records(df: pd.DataFrame) -> list[dict]:
    """Only the columns the client visuals need, NaN-safe for JSON."""
    recs = []
    for r in df.itertuples(index=False):
        month = r.month if isinstance(r.month, str) and "-" in r.month else None
        recs.append({
            "reference": str(r.reference),
            "break_type": str(r.break_type),
            "is_break": int(r.is_break),
            "ledger_amount": None if pd.isna(r.ledger_amount) else float(r.ledger_amount),
            "value_at_risk": 0.0 if pd.isna(r.value_at_risk) else float(r.value_at_risk),
            "currency": None if pd.isna(r.currency) else str(r.currency),
            "month": month,
            "decision": str(r.decision),
            "llm_category": None if pd.isna(r.llm_category) else str(r.llm_category),
            "confidence": None if pd.isna(r.confidence) else float(r.confidence),
        })
    return recs


# ── page assembly ──────────────────────────────────────────────────────
def build_html() -> str:
    df = export_powerbi.build()
    data_json = json.dumps(_records(df)).replace("<", "\\u003c")
    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "provider": ("groq" if config.active_llm_key()
                     not in (None, "your-groq-key-here") else "offline"),
        "palette": CAT,
        "decisionHue": DECISION_HUE,
        "causeOrder": CAUSE_ORDER,
        "decisionOrder": DECISION_ORDER,
        "glossary": _glossary(),
    }
    meta_json = json.dumps(meta).replace("<", "\\u003c")
    data_script = (f"<script>\nwindow.DATA = {data_json};\n"
                   f"window.META = {meta_json};\n</script>\n")
    return HEAD + STYLE + BODY + data_script + SCRIPT + "</body></html>"


# ── static markup (no interpolation -> plain strings, brace-safe) ──────
HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinRecon Copilot - Reconciliation Dashboard</title>
"""

STYLE = """<style>
:root {
  --plane:#f9f9f7; --surface-1:#fcfcfb; --text-primary:#0b0b0b;
  --text-secondary:#52514e; --muted:#898781; --grid:#e1e0d9; --baseline:#c3c2b7;
  --series-1:#2a78d6; --good:#006300; --border:rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --plane:#0d0d0d; --surface-1:#1a1a19; --text-primary:#fff;
    --text-secondary:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --baseline:#383835;
    --series-1:#3987e5; --good:#0ca30c; --border:rgba(255,255,255,0.10);
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--plane); color:var(--text-primary);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:24px 20px 48px; }
header h1 { margin:0 0 2px; font-size:22px; }
header p { margin:0; color:var(--text-secondary); font-size:13px; }
.slicers { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end;
  margin:18px 0 8px; padding:14px 16px; background:var(--surface-1);
  border:1px solid var(--border); border-radius:12px; }
.slicer { display:flex; flex-direction:column; gap:6px; }
.slicer > label { font-size:11px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); }
.pills { display:flex; flex-wrap:wrap; gap:6px; }
.pill-btn { font-size:12px; padding:3px 10px; border-radius:999px;
  border:1.5px solid var(--border); background:transparent;
  color:var(--text-secondary); cursor:pointer; }
.pill-btn.on { color:#fff; border-color:transparent; }
select, input[type=search] { font:inherit; font-size:13px; padding:5px 8px;
  border-radius:8px; border:1px solid var(--border); background:var(--surface-1);
  color:var(--text-primary); }
#sl-reset { align-self:flex-end; font-size:12px; padding:6px 12px;
  border-radius:8px; border:1px solid var(--border); background:transparent;
  color:var(--text-secondary); cursor:pointer; }
#active-summary { font-size:12px; color:var(--muted); margin:0 2px 14px; }
details.glossary { margin:0 0 20px; }
details.glossary > summary { cursor:pointer; font-size:14px; list-style:none; }
details.glossary > summary::-webkit-details-marker { display:none; }
details.glossary > summary::before { content:"\\25B8"; margin-right:8px; color:var(--muted); }
details.glossary[open] > summary::before { content:"\\25BE"; }
.gloss-intro { font-size:13px; color:var(--text-secondary); margin:12px 0 4px;
  line-height:1.5; }
.gloss-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px 26px; margin-top:10px; }
.gloss-block { min-width:0; }
.gloss-block h3 { font-size:12px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); margin:10px 0 6px; }
.gloss-row { display:flex; gap:9px; padding:5px 0; font-size:13px;
  border-bottom:1px solid var(--grid); align-items:baseline; }
.gloss-term { font-weight:600; white-space:nowrap; }
.gloss-term.mono { font-family:ui-monospace,Consolas,monospace; font-weight:500; }
.gloss-desc { color:var(--text-secondary); line-height:1.4; }
.gloss-sw { display:inline-block; width:10px; height:10px; border-radius:3px;
  flex:0 0 auto; margin-top:4px; }
.help { border-bottom:1px dotted var(--muted); cursor:help; }
.grid-kpi { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:12px 0 20px; }
.kpi { background:var(--surface-1); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; }
.kpi-label { font-size:12px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.04em; }
.kpi-num { font-size:30px; font-weight:700; margin-top:6px; }
.kpi-num.good { color:var(--good); }
.kpi-sub { font-size:12px; color:var(--text-secondary); margin-top:2px; }
.cards { display:grid; grid-template-columns:1.3fr 1fr; gap:16px; }
.card { background:var(--surface-1); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; margin-bottom:16px; }
.card h2 { margin:0 0 12px; font-size:14px; }
.full { grid-column:1 / -1; }
.center { display:flex; align-items:center; gap:18px; flex-wrap:wrap; justify-content:center; }
.legend { display:flex; flex-direction:column; gap:8px; }
.lg { font-size:13px; color:var(--text-secondary); cursor:pointer; }
.lg.off { opacity:0.4; }
.sw { display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:7px; vertical-align:middle; }
text.cat { font-size:12px; fill:var(--text-secondary); }
text.val { font-size:12px; fill:var(--text-primary); font-weight:600; }
text.axis { font-size:11px; fill:var(--muted); }
line.grid { stroke:var(--grid); stroke-width:1; }
.clk { cursor:pointer; }
.donut-num { font-size:24px; font-weight:700; fill:var(--text-primary); }
.donut-cap { font-size:11px; fill:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--grid); }
th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
td.mono { font-family:ui-monospace,Consolas,monospace; }
.pill { font-size:11px; border:1.5px solid; border-radius:999px; padding:1px 8px; }
.muted { color:var(--muted); font-size:13px; }
footer { margin-top:18px; color:var(--muted); font-size:12px; text-align:center; }
</style></head>
"""

BODY = """<body><div class="wrap">
<header>
  <h1>FinRecon Copilot &mdash; Reconciliation Dashboard</h1>
  <p id="subtitle">Ledger vs bank feed &bull; synthetic data</p>
</header>

<div class="slicers">
  <div class="slicer"><label>Decision</label><div id="sl-decision" class="pills"></div></div>
  <div class="slicer"><label>Cause</label><div id="sl-cause" class="pills"></div></div>
  <div class="slicer"><label>Month</label><select id="sl-month"></select></div>
  <div class="slicer"><label>Currency</label><select id="sl-currency"></select></div>
  <div class="slicer"><label>Search reference</label>
    <input id="sl-search" type="search" placeholder="reference&hellip;"></div>
  <button id="sl-reset" type="button">Reset filters</button>
</div>
<div id="active-summary"></div>

<details class="card glossary" id="glossary" open>
  <summary><b>How to read this dashboard</b> &mdash; what each label means
    <span class="muted">(click to collapse)</span></summary>
  <div id="glossary-body"></div>
</details>

<div class="grid-kpi" id="kpis"></div>

<div class="cards">
  <div class="card">
    <h2>Breaks by cause (count)</h2>
    <div id="chart-cause-n"></div>
  </div>
  <div class="card">
    <h2>Decision mix</h2>
    <div class="center"><div id="chart-donut"></div>
      <div class="legend" id="donut-legend"></div></div>
  </div>
  <div class="card full">
    <h2>Value at risk by month</h2>
    <div id="chart-month"></div>
  </div>
  <div class="card">
    <h2>Value at risk by cause</h2>
    <div id="chart-cause-var"></div>
  </div>
  <div class="card">
    <h2>Breaks by cause (table view)</h2>
    <table><thead><tr><th>Cause</th><th class="num">Count</th>
    <th class="num">Value at risk</th></tr></thead>
    <tbody id="cause-table"></tbody></table>
  </div>
  <div class="card full">
    <h2 id="queue-title">Approvals queue &mdash; human-in-the-loop</h2>
    <table><thead><tr><th>Reference</th><th>Cause</th><th class="num">Value at risk</th>
    <th>AI category</th><th class="num">Conf.</th><th>Decision</th></tr></thead>
    <tbody id="queue-table"></tbody></table>
  </div>
</div>

<footer>Rules for the math &bull; AI for the language &bull; human for the decisions
&nbsp;|&nbsp; FinRecon Copilot</footer>
</div>
"""

SCRIPT = """<script>
(function () {
  const DATA = window.DATA, META = window.META;
  const CAT = META.palette, DHUE = META.decisionHue;
  const CAUSE_ORDER = META.causeOrder, DEC_ORDER = META.decisionOrder;

  // ── formatting ───────────────────────────────────────────────────────
  const nf = new Intl.NumberFormat("en-US");
  const money = v => "$" + nf.format(Math.round(v));
  function moneyShort(v) {
    const a = Math.abs(v);
    if (a >= 1e9) return "$" + (v / 1e9).toFixed(1) + "B";
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
    if (a >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
    return "$" + nf.format(Math.round(v));
  }
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = (s === null || s === undefined) ? "" : String(s);
    return d.innerHTML;
  }
  const decHue = d => CAT[DHUE[d]] || CAT.blue;
  const monthLabel = m => m.slice(5, 7) + "/" + m.slice(2, 4);
  const titleAttr = t => t ? ' title="' + esc(t) + '"' : "";

  // ── plain-English definitions (from META.glossary) ───────────────────
  const G = META.glossary;
  const DESC = { decision: {}, cause: {}, category: {} };
  G.decision.rows.forEach(r => { DESC.decision[r[0]] = r[2]; });
  G.cause.rows.forEach(r => { DESC.cause[r[0]] = r[2]; });
  G.category.rows.forEach(r => { DESC.category[r[0]] = r[1]; });

  function renderGlossary() {
    const blocks = [["decision", G.decision], ["cause", G.cause],
                    ["category", G.category], ["metric", G.metric]];
    let h = '<p class="gloss-intro">' + esc(G.intro) + '</p><div class="gloss-grid">';
    blocks.forEach(pair => {
      const key = pair[0], b = pair[1];
      h += '<div class="gloss-block"><h3>' + esc(b.title) + '</h3>';
      b.rows.forEach(r => {
        const swatch = b.kind === "swatch";
        const term = r[0], desc = swatch ? r[2] : r[1];
        const sw = swatch
          ? '<span class="gloss-sw" style="background:' + r[1] + '"></span>' : "";
        const mono = key === "metric" ? "" : " mono";
        h += '<div class="gloss-row">' + sw + '<span class="gloss-term' + mono +
          '">' + esc(term) + '</span><span class="gloss-desc">' + esc(desc) +
          '</span></div>';
      });
      h += "</div>";
    });
    h += "</div>";
    document.getElementById("glossary-body").innerHTML = h;
  }

  // ── chart builders (SVG strings) ─────────────────────────────────────
  function hbar(rows, unit, color, filterKey) {
    if (!rows.length) return "<p class='muted'>No data.</p>";
    const width = 440, rowH = 34, padLeft = 140, barW = width - padLeft - 70;
    const maxv = Math.max.apply(null, rows.map(r => r[1])) || 1;
    const h = rowH * rows.length + 10;
    const out = ['<svg viewBox="0 0 ' + width + ' ' + h +
      '" role="img" width="100%" height="' + h + '">'];
    rows.forEach((r, i) => {
      const label = r[0], v = r[1], y = i * rowH + 6;
      const w = Math.max(2, barW * v / maxv);
      const val = unit === "$" ? money(v) : String(Math.round(v));
      const clk = filterKey
        ? ' class="clk" data-filter="' + filterKey + '" data-value="' + esc(label) + '"'
        : "";
      out.push('<text x="' + (padLeft - 8) + '" y="' + (y + 16) +
        '" text-anchor="end" class="cat">' + esc(label) + '</text>');
      out.push('<rect x="' + padLeft + '" y="' + (y + 4) + '" width="' + w.toFixed(1) +
        '" height="18" rx="4" fill="' + color + '"' + clk + '><title>' + esc(label) +
        ': ' + esc(val) + '</title></rect>');
      out.push('<text x="' + (padLeft + w + 6).toFixed(1) + '" y="' + (y + 18) +
        '" class="val">' + esc(val) + '</text>');
    });
    out.push("</svg>");
    return out.join("");
  }

  function donut(rows, size, thick) {
    size = size || 190; thick = thick || 34;
    const total = rows.reduce((s, r) => s + r[1], 0) || 1;
    const r = (size - thick) / 2, cx = size / 2, cy = size / 2, C = 2 * Math.PI * r;
    const out = ['<svg viewBox="0 0 ' + size + ' ' + size + '" width="' + size +
      '" height="' + size + '" role="img">'];
    let acc = 0;
    rows.forEach(row => {
      const label = row[0], v = row[1], color = row[2];
      const frac = v / total, dash = frac * C;
      out.push('<circle class="clk" data-filter="decision" data-value="' + esc(label) +
        '" cx="' + cx + '" cy="' + cy + '" r="' + r.toFixed(2) +
        '" fill="none" stroke="' + color + '" stroke-width="' + thick +
        '" stroke-dasharray="' + dash.toFixed(2) + ' ' + (C - dash).toFixed(2) +
        '" stroke-dashoffset="' + (-acc * C).toFixed(2) +
        '" transform="rotate(-90 ' + cx + ' ' + cy + ')"><title>' + esc(label) +
        ': ' + Math.round(v) + ' (' + Math.round(frac * 100) + '%)</title></circle>');
      acc += frac;
    });
    out.push('<text x="' + cx + '" y="' + (cy - 2) +
      '" text-anchor="middle" class="donut-num">' + Math.round(total) + '</text>' +
      '<text x="' + cx + '" y="' + (cy + 16) +
      '" text-anchor="middle" class="donut-cap">items</text></svg>');
    return out.join("");
  }

  function areaLine(points, width, height, pad) {
    width = width || 560; height = height || 210; pad = pad || 40;
    if (!points.length) return "<p class='muted'>No data.</p>";
    const maxv = Math.max.apply(null, points.map(p => p[1])) || 1;
    const n = points.length, plotW = width - pad - 12, plotH = height - pad - 24;
    const xs = points.map((_, i) => pad + plotW * i / (n > 1 ? n - 1 : 1));
    const ys = points.map(p => pad / 2 + plotH * (1 - p[1] / maxv));
    const base = pad / 2 + plotH;
    const out = ['<svg viewBox="0 0 ' + width + ' ' + height + '" width="100%" height="' +
      height + '" role="img">'];
    for (let g = 0; g < 5; g++) {
      const gy = pad / 2 + plotH * g / 4, gv = maxv * (1 - g / 4);
      out.push('<line x1="' + pad + '" y1="' + gy.toFixed(1) + '" x2="' + (width - 12) +
        '" y2="' + gy.toFixed(1) + '" class="grid"/>');
      out.push('<text x="' + (pad - 6) + '" y="' + (gy + 3).toFixed(1) +
        '" text-anchor="end" class="axis">' + esc(moneyShort(gv)) + '</text>');
    }
    let area = "M " + xs[0].toFixed(1) + " " + base.toFixed(1) + " ";
    area += xs.map((x, i) => "L " + x.toFixed(1) + " " + ys[i].toFixed(1)).join(" ");
    area += " L " + xs[n - 1].toFixed(1) + " " + base.toFixed(1) + " Z";
    out.push('<path d="' + area + '" fill="var(--series-1)" opacity="0.12"/>');
    let line = "M " + xs[0].toFixed(1) + " " + ys[0].toFixed(1) + " ";
    line += xs.slice(1).map((x, i) => "L " + x.toFixed(1) + " " + ys[i + 1].toFixed(1)).join(" ");
    out.push('<path d="' + line + '" fill="none" stroke="var(--series-1)" stroke-width="2"/>');
    points.forEach((p, i) => {
      out.push('<circle cx="' + xs[i].toFixed(1) + '" cy="' + ys[i].toFixed(1) +
        '" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>' +
        esc(p[0]) + ': ' + esc(money(p[1])) + '</title></circle>');
      out.push('<text x="' + xs[i].toFixed(1) + '" y="' + (height - 8) +
        '" text-anchor="middle" class="axis">' + esc(p[0]) + '</text>');
    });
    out.push("</svg>");
    return out.join("");
  }

  // ── filter state ─────────────────────────────────────────────────────
  const state = { decision: new Set(), cause: new Set(), month: "", currency: "", search: "" };

  function applyFilters() {
    const q = state.search.trim().toLowerCase();
    return DATA.filter(d => {
      if (state.decision.size && !state.decision.has(d.decision)) return false;
      if (state.cause.size && !state.cause.has(d.break_type)) return false;
      if (state.month && d.month !== state.month) return false;
      if (state.currency && d.currency !== state.currency) return false;
      if (q && !(d.reference || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }

  // ── slicer population ────────────────────────────────────────────────
  function uniqueSorted(key) {
    return Array.from(new Set(DATA.map(d => d[key]).filter(v => v != null))).sort();
  }
  function buildPills(containerId, values, stateKey, hueFn, descMap) {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    values.forEach(v => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "pill-btn"; b.textContent = v;
      b.dataset.value = v; b.dataset.hue = hueFn ? hueFn(v) : CAT.blue;
      if (descMap && descMap[v]) b.title = descMap[v];
      b.addEventListener("click", () => toggle(stateKey, v));
      el.appendChild(b);
    });
  }
  function fillSelect(id, values, label) {
    const el = document.getElementById(id);
    el.innerHTML = '<option value="">' + label + '</option>' +
      values.map(v => '<option value="' + esc(v) + '">' + esc(v) + '</option>').join("");
  }

  function toggle(key, value) {
    const set = state[key];
    if (set.has(value)) set.delete(value); else set.add(value);
    render();
  }

  // ── render ───────────────────────────────────────────────────────────
  function render() {
    const rows = applyFilters();
    const breaks = rows.filter(d => d.is_break === 1);
    const total = rows.length, nBreaks = breaks.length, matched = total - nBreaks;
    const ledgerTotal = rows.filter(d => d.ledger_amount != null).length;
    const matchRate = ledgerTotal ? 100 * matched / ledgerTotal : 0;
    const varTotal = breaks.reduce((s, d) => s + d.value_at_risk, 0);
    const humanQ = rows.filter(d =>
      d.decision === "HUMAN" || d.decision === "NEEDS_REVIEW").length;

    // KPIs
    document.getElementById("kpis").innerHTML =
      kpi("Match rate", matchRate.toFixed(1) + "%",
          matched + " of " + ledgerTotal + " ledger matched", "good") +
      kpi("Breaks found", String(nBreaks), "in current view") +
      kpi("Value at risk", moneyShort(varTotal), money(varTotal)) +
      kpi("Human review", String(humanQ), "need approval");

    // breaks by cause
    const causeN = [], causeVar = [], causeTable = [];
    CAUSE_ORDER.forEach(c => {
      const rowsC = breaks.filter(d => d.break_type === c);
      if (!rowsC.length) return;
      const n = rowsC.length, v = rowsC.reduce((s, d) => s + d.value_at_risk, 0);
      causeN.push([c, n]); causeVar.push([c, v]);
      causeTable.push('<tr><td class="help"' + titleAttr(DESC.cause[c]) + '>' +
        esc(c) + '</td><td class="num">' + n +
        '</td><td class="num">' + esc(money(v)) + '</td></tr>');
    });
    document.getElementById("chart-cause-n").innerHTML =
      hbar(causeN, "n", "var(--series-1)", "cause");
    document.getElementById("chart-cause-var").innerHTML =
      hbar(causeVar, "$", "var(--series-1)", "cause");
    document.getElementById("cause-table").innerHTML =
      causeTable.join("") || '<tr><td colspan="3" class="muted">No breaks.</td></tr>';

    // value at risk by month
    const byMonth = {};
    breaks.forEach(d => { if (d.month) byMonth[d.month] = (byMonth[d.month] || 0) + d.value_at_risk; });
    const monthRows = Object.keys(byMonth).sort().map(m => [monthLabel(m), byMonth[m]]);
    document.getElementById("chart-month").innerHTML = areaLine(monthRows);

    // decision donut
    const decCounts = {};
    rows.forEach(d => { decCounts[d.decision] = (decCounts[d.decision] || 0) + 1; });
    const decRows = DEC_ORDER.filter(d => decCounts[d])
      .map(d => [d, decCounts[d], decHue(d)]);
    document.getElementById("chart-donut").innerHTML = donut(decRows);
    document.getElementById("donut-legend").innerHTML = decRows.map(r =>
      '<span class="lg clk" data-filter="decision" data-value="' + esc(r[0]) + '"' +
      titleAttr(DESC.decision[r[0]]) + '><span class="sw" style="background:' + r[2] +
      '"></span>' + esc(r[0]) + ' <b>' + Math.round(r[1]) + '</b></span>').join("");

    // approvals queue - ALL filtered human-review breaks, highest value first
    const queue = breaks
      .filter(d => d.decision === "HUMAN" || d.decision === "NEEDS_REVIEW")
      .sort((a, b) => b.value_at_risk - a.value_at_risk);
    document.getElementById("queue-title").innerHTML =
      "Approvals queue &mdash; human-in-the-loop (all " + queue.length + " by value)";
    document.getElementById("queue-table").innerHTML = queue.map(d =>
      '<tr><td class="mono">' + esc(d.reference) + '</td><td class="help"' +
      titleAttr(DESC.cause[d.break_type]) + '>' + esc(d.break_type) +
      '</td><td class="num">' + esc(money(d.value_at_risk)) + '</td><td class="help"' +
      titleAttr(DESC.category[d.llm_category]) + '>' + esc(d.llm_category || "-") +
      '</td><td class="num">' +
      (d.confidence != null ? d.confidence.toFixed(2) : "-") +
      '</td><td><span class="pill" style="border-color:' + decHue(d.decision) + '"' +
      titleAttr(DESC.decision[d.decision]) + '>' +
      esc(d.decision) + '</span></td></tr>').join("") ||
      '<tr><td colspan="6" class="muted">No items in the approvals queue for this filter.</td></tr>';

    syncControls(rows.length);
  }

  function kpi(label, value, sub, accent) {
    return '<div class="kpi"><div class="kpi-label">' + esc(label) +
      '</div><div class="kpi-num ' + (accent || "") + '">' + esc(value) +
      '</div><div class="kpi-sub">' + esc(sub) + '</div></div>';
  }

  // reflect active state on the pills + summary line
  function syncControls(shown) {
    document.querySelectorAll("#sl-decision .pill-btn").forEach(b => {
      const on = state.decision.has(b.dataset.value);
      b.classList.toggle("on", on);
      b.style.background = on ? b.dataset.hue : "";
    });
    document.querySelectorAll("#sl-cause .pill-btn").forEach(b => {
      const on = state.cause.has(b.dataset.value);
      b.classList.toggle("on", on);
      b.style.background = on ? "var(--series-1)" : "";
    });
    const parts = [];
    if (state.decision.size) parts.push("decision: " + Array.from(state.decision).join(", "));
    if (state.cause.size) parts.push("cause: " + Array.from(state.cause).join(", "));
    if (state.month) parts.push("month: " + state.month);
    if (state.currency) parts.push("currency: " + state.currency);
    if (state.search.trim()) parts.push('ref ~ "' + state.search.trim() + '"');
    document.getElementById("active-summary").textContent =
      "Showing " + shown + " of " + DATA.length + " rows" +
      (parts.length ? "  \\u2022  filters \\u2014 " + parts.join("  \\u2022  ") : "  \\u2022  no filters");
  }

  // ── wiring ───────────────────────────────────────────────────────────
  function init() {
    document.getElementById("subtitle").textContent =
      "Ledger vs bank feed \\u2022 generated " + META.generated +
      " \\u2022 LLM: " + META.provider + " \\u2022 synthetic data";

    const decPresent = DEC_ORDER.filter(d => DATA.some(x => x.decision === d));
    const causePresent = CAUSE_ORDER.filter(c => DATA.some(x => x.break_type === c));
    buildPills("sl-decision", decPresent, "decision", decHue, DESC.decision);
    buildPills("sl-cause", causePresent, "cause", null, DESC.cause);
    fillSelect("sl-month", uniqueSorted("month"), "All months");
    fillSelect("sl-currency", uniqueSorted("currency"), "All currencies");
    renderGlossary();

    document.getElementById("sl-month").addEventListener("change", e => {
      state.month = e.target.value; render();
    });
    document.getElementById("sl-currency").addEventListener("change", e => {
      state.currency = e.target.value; render();
    });
    document.getElementById("sl-search").addEventListener("input", e => {
      state.search = e.target.value; render();
    });
    document.getElementById("sl-reset").addEventListener("click", () => {
      state.decision.clear(); state.cause.clear();
      state.month = ""; state.currency = ""; state.search = "";
      document.getElementById("sl-month").value = "";
      document.getElementById("sl-currency").value = "";
      document.getElementById("sl-search").value = "";
      render();
    });

    // charts / legend as slicers (event delegation)
    document.querySelector(".cards").addEventListener("click", e => {
      const t = e.target.closest("[data-filter]");
      if (!t) return;
      toggle(t.dataset.filter, t.dataset.value);
    });

    render();
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
</script>
"""


def main() -> int:
    OUT.write_text(build_html(), encoding="utf-8")
    print(f"[dashboard] wrote {OUT}")
    print(f"[dashboard] open it in a browser:  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
