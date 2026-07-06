"""
Phase 7 (local dashboard) - render a self-contained HTML dashboard.

Turns the reconciliation result into a clean, browser-viewable dashboard
(KPI cards + charts + approvals table) with NO Power BI and NO internet:
everything is inline SVG + CSS in one .html file you can double-click.

Colours use the validated data-viz reference palette; every chart carries
direct labels and a legend so identity never rests on colour alone. Light
and dark mode both ship (prefers-color-scheme).

Run:   python -m src.make_dashboard      (after run.py)
Out:   reports/dashboard.html
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import export_powerbi  # noqa: E402

OUT = config.REPORTS_DIR / "dashboard.html"

# Validated categorical hues (light / dark) from the reference palette.
CAT = {
    "blue":   ("#2a78d6", "#3987e5"),
    "aqua":   ("#1baf7a", "#199e70"),
    "yellow": ("#eda100", "#c98500"),
    "green":  ("#008300", "#008300"),
    "orange": ("#eb6834", "#d95926"),
    "red":    ("#e34948", "#e66767"),
}
DECISION_HUE = {  # decision -> palette slot (carries meaning, always labelled)
    "MATCHED": "green", "AUTO": "blue", "HUMAN": "orange", "NEEDS_REVIEW": "yellow",
    "QUARANTINE": "red",
}
CAUSE_ORDER = ["amount-mismatch", "missing-in-bank", "missing-in-ledger", "duplicate"]


# ── formatting helpers ─────────────────────────────────────────────────
def money(v: float) -> str:
    return f"${v:,.0f}"


def money_short(v: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v/div:.1f}{unit}"
    return f"${v:,.0f}"


def esc(s) -> str:
    return html.escape(str(s))


# ── SVG chart builders ─────────────────────────────────────────────────
def hbar(rows: list[tuple[str, float]], *, unit: str, width=440, row_h=34,
         pad_left=140, color="var(--series-1)") -> str:
    """Horizontal bar chart with a category label and a direct value label."""
    if not rows:
        return "<p class='muted'>No data.</p>"
    maxv = max(v for _, v in rows) or 1
    bar_w = width - pad_left - 70
    h = row_h * len(rows) + 10
    out = [f'<svg viewBox="0 0 {width} {h}" role="img" width="100%" height="{h}">']
    for i, (label, v) in enumerate(rows):
        y = i * row_h + 6
        w = max(2, bar_w * v / maxv)
        val = money(v) if unit == "$" else f"{int(v)}"
        out.append(
            f'<text x="{pad_left-8}" y="{y+16}" text-anchor="end" '
            f'class="cat">{esc(label)}</text>')
        out.append(
            f'<rect x="{pad_left}" y="{y+4}" width="{w:.1f}" height="18" rx="4" '
            f'fill="{color}"><title>{esc(label)}: {esc(val)}</title></rect>')
        out.append(
            f'<text x="{pad_left+w+6:.1f}" y="{y+18}" class="val">{esc(val)}</text>')
    out.append("</svg>")
    return "".join(out)


def donut(rows: list[tuple[str, float, str]], *, size=190, thick=34) -> str:
    """Donut via stroke-dasharray. rows = (label, value, hexcolor)."""
    total = sum(v for _, v, _ in rows) or 1
    r = (size - thick) / 2
    cx = cy = size / 2
    import math
    C = 2 * math.pi * r
    out = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
           f'role="img">']
    acc = 0.0
    for label, v, color in rows:
        frac = v / total
        dash = frac * C
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r:.2f}" fill="none" '
            f'stroke="{color}" stroke-width="{thick}" '
            f'stroke-dasharray="{dash:.2f} {C-dash:.2f}" '
            f'stroke-dashoffset="{-acc*C:.2f}" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'<title>{esc(label)}: {int(v)} ({frac*100:.0f}%)</title></circle>')
        acc += frac
    out.append(
        f'<text x="{cx}" y="{cy-2}" text-anchor="middle" class="donut-num">'
        f'{int(total)}</text>'
        f'<text x="{cx}" y="{cy+16}" text-anchor="middle" class="donut-cap">'
        f'items</text>')
    out.append("</svg>")
    return "".join(out)


def area_line(points: list[tuple[str, float]], *, width=560, height=210,
              pad=40) -> str:
    """Area + line trend with point markers and y-gridlines."""
    if not points:
        return "<p class='muted'>No data.</p>"
    maxv = max(v for _, v in points) or 1
    n = len(points)
    plot_w = width - pad - 12
    plot_h = height - pad - 24
    xs = [pad + (plot_w * i / (n - 1 if n > 1 else 1)) for i in range(n)]
    ys = [pad/2 + plot_h * (1 - v / maxv) for _, v in points]
    base = pad/2 + plot_h
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
           f'role="img">']
    # gridlines + y labels
    for g in range(5):
        gy = pad/2 + plot_h * g / 4
        gv = maxv * (1 - g / 4)
        out.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{width-12}" y2="{gy:.1f}" '
                   f'class="grid"/>')
        out.append(f'<text x="{pad-6}" y="{gy+3:.1f}" text-anchor="end" '
                   f'class="axis">{esc(money_short(gv))}</text>')
    # area
    area = f'M {xs[0]:.1f} {base:.1f} ' + " ".join(
        f'L {x:.1f} {y:.1f}' for x, y in zip(xs, ys)) + \
        f' L {xs[-1]:.1f} {base:.1f} Z'
    out.append(f'<path d="{area}" fill="var(--series-1)" opacity="0.12"/>')
    # line
    line = f'M {xs[0]:.1f} {ys[0]:.1f} ' + " ".join(
        f'L {x:.1f} {y:.1f}' for x, y in zip(xs[1:], ys[1:]))
    out.append(f'<path d="{line}" fill="none" stroke="var(--series-1)" '
               f'stroke-width="2"/>')
    # markers + x labels
    for (label, v), x, y in zip(points, xs, ys):
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--series-1)" '
                   f'stroke="var(--surface-1)" stroke-width="2">'
                   f'<title>{esc(label)}: {esc(money(v))}</title></circle>')
        out.append(f'<text x="{x:.1f}" y="{height-8}" text-anchor="middle" '
                   f'class="axis">{esc(label)}</text>')
    out.append("</svg>")
    return "".join(out)


# ── page assembly ──────────────────────────────────────────────────────
def build_html() -> str:
    df = export_powerbi.build()
    breaks = df[df["is_break"] == 1]
    total = len(df)
    n_breaks = len(breaks)
    matched = total - n_breaks
    # Match rate is matched / LEDGER references (not all refs) to stay consistent
    # with the SQL/pandas pipeline. Bank-only refs (missing-in-ledger) have no
    # ledger_amount and are excluded from the denominator.
    ledger_total = int(df["ledger_amount"].notna().sum())
    match_rate = 100.0 * matched / ledger_total if ledger_total else 0
    var = float(breaks["value_at_risk"].sum())
    dec_counts = df["decision"].value_counts().to_dict()
    human_q = int(dec_counts.get("HUMAN", 0) + dec_counts.get("NEEDS_REVIEW", 0))

    # breaks by cause (count + value)
    cause = (breaks.groupby("break_type")
             .agg(n=("reference", "size"), var=("value_at_risk", "sum")))
    cause_rows = [(c, int(cause.loc[c, "n"])) for c in CAUSE_ORDER if c in cause.index]
    causevar_rows = [(c, float(cause.loc[c, "var"])) for c in CAUSE_ORDER
                     if c in cause.index]

    # value at risk by month
    vm = breaks.groupby("month")["value_at_risk"].sum().sort_index()
    month_rows = [(m.split("-")[1] + "/" + m.split("-")[0][2:], float(v))
                  for m, v in vm.items() if isinstance(m, str) and "-" in m]

    # decision donut (light hues)
    dec_rows = []
    for d in ["MATCHED", "AUTO", "HUMAN", "NEEDS_REVIEW", "QUARANTINE"]:
        if dec_counts.get(d):
            dec_rows.append((d, float(dec_counts[d]), CAT[DECISION_HUE[d]][0]))

    # approvals queue (top by value)
    queue = (breaks[breaks["decision"].isin(["HUMAN", "NEEDS_REVIEW"])]
             .sort_values("value_at_risk", ascending=False).head(15))

    def kpi(label, value, sub, accent=""):
        cls = f" kpi-num {accent}".rstrip()
        return (f'<div class="kpi"><div class="kpi-label">{esc(label)}</div>'
                f'<div class="{cls}">{esc(value)}</div>'
                f'<div class="kpi-sub">{esc(sub)}</div></div>')

    # decision legend + queue rows
    legend = "".join(
        f'<span class="lg"><span class="sw" style="background:{CAT[DECISION_HUE[d]][0]}">'
        f'</span>{esc(d)} <b>{int(v)}</b></span>'
        for d, v, _ in dec_rows)

    qrows = "".join(
        f'<tr><td class="mono">{esc(r.reference)}</td><td>{esc(r.break_type)}</td>'
        f'<td class="num">{esc(money(r.value_at_risk))}</td>'
        f'<td>{esc(r.llm_category if r.llm_category==r.llm_category else "-")}</td>'
        f'<td class="num">{("%.2f"%r.confidence) if r.confidence==r.confidence else "-"}</td>'
        f'<td><span class="pill" style="border-color:{CAT[DECISION_HUE[r.decision]][0]}">'
        f'{esc(r.decision)}</span></td></tr>'
        for r in queue.itertuples(index=False))

    cause_table = "".join(
        f'<tr><td>{esc(c)}</td><td class="num">{int(cause.loc[c,"n"])}</td>'
        f'<td class="num">{esc(money(cause.loc[c,"var"]))}</td></tr>'
        for c in CAUSE_ORDER if c in cause.index)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    provider = "groq" if config.active_llm_key() not in (None, "your-groq-key-here") else "offline"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinRecon Copilot - Reconciliation Dashboard</title>
<style>
:root {{
  --plane:#f9f9f7; --surface-1:#fcfcfb; --text-primary:#0b0b0b;
  --text-secondary:#52514e; --muted:#898781; --grid:#e1e0d9; --baseline:#c3c2b7;
  --series-1:#2a78d6; --good:#006300; --border:rgba(11,11,11,0.10);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --plane:#0d0d0d; --surface-1:#1a1a19; --text-primary:#fff;
    --text-secondary:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --baseline:#383835;
    --series-1:#3987e5; --good:#0ca30c; --border:rgba(255,255,255,0.10);
  }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--plane); color:var(--text-primary);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:24px 20px 48px; }}
header h1 {{ margin:0 0 2px; font-size:22px; }}
header p {{ margin:0; color:var(--text-secondary); font-size:13px; }}
.grid-kpi {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0; }}
.kpi {{ background:var(--surface-1); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; }}
.kpi-label {{ font-size:12px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.04em; }}
.kpi-num {{ font-size:30px; font-weight:700; margin-top:6px; }}
.kpi-num.good {{ color:var(--good); }}
.kpi-sub {{ font-size:12px; color:var(--text-secondary); margin-top:2px; }}
.cards {{ display:grid; grid-template-columns:1.3fr 1fr; gap:16px; }}
.card {{ background:var(--surface-1); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; margin-bottom:16px; }}
.card h2 {{ margin:0 0 12px; font-size:14px; }}
.full {{ grid-column:1 / -1; }}
.center {{ display:flex; align-items:center; gap:18px; flex-wrap:wrap; justify-content:center; }}
.legend {{ display:flex; flex-direction:column; gap:8px; }}
.lg {{ font-size:13px; color:var(--text-secondary); }}
.sw {{ display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:7px; vertical-align:middle; }}
text.cat {{ font-size:12px; fill:var(--text-secondary); }}
text.val {{ font-size:12px; fill:var(--text-primary); font-weight:600; }}
text.axis {{ font-size:11px; fill:var(--muted); }}
line.grid {{ stroke:var(--grid); stroke-width:1; }}
.donut-num {{ font-size:24px; font-weight:700; fill:var(--text-primary); }}
.donut-cap {{ font-size:11px; fill:var(--muted); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ text-align:left; padding:7px 8px; border-bottom:1px solid var(--grid); }}
th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; }}
td.num,th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.mono {{ font-family:ui-monospace,Consolas,monospace; }}
.pill {{ font-size:11px; border:1.5px solid; border-radius:999px; padding:1px 8px; }}
.muted {{ color:var(--muted); font-size:13px; }}
footer {{ margin-top:18px; color:var(--muted); font-size:12px; text-align:center; }}
</style></head>
<body><div class="wrap">
<header>
  <h1>FinRecon Copilot &mdash; Reconciliation Dashboard</h1>
  <p>Ledger vs bank feed &bull; generated {ts} &bull; LLM: {esc(provider)} &bull; synthetic data</p>
</header>

<div class="grid-kpi">
  {kpi("Match rate", f"{match_rate:.1f}%", f"{matched} of {ledger_total} ledger matched", "good")}
  {kpi("Breaks found", f"{n_breaks}", "across 4 causes")}
  {kpi("Value at risk", money_short(var), money(var))}
  {kpi("Human review", f"{human_q}", "need approval")}
</div>

<div class="cards">
  <div class="card">
    <h2>Breaks by cause (count)</h2>
    {hbar(cause_rows, unit="n")}
  </div>
  <div class="card">
    <h2>Decision mix</h2>
    <div class="center">{donut(dec_rows)}<div class="legend">{legend}</div></div>
  </div>
  <div class="card full">
    <h2>Value at risk by month</h2>
    {area_line(month_rows)}
  </div>
  <div class="card">
    <h2>Value at risk by cause</h2>
    {hbar(causevar_rows, unit="$")}
  </div>
  <div class="card">
    <h2>Breaks by cause (table view)</h2>
    <table><thead><tr><th>Cause</th><th class="num">Count</th>
    <th class="num">Value at risk</th></tr></thead><tbody>{cause_table}</tbody></table>
  </div>
  <div class="card full">
    <h2>Approvals queue &mdash; human-in-the-loop (top {len(queue)} by value)</h2>
    <table><thead><tr><th>Reference</th><th>Cause</th><th class="num">Value at risk</th>
    <th>AI category</th><th class="num">Conf.</th><th>Decision</th></tr></thead>
    <tbody>{qrows}</tbody></table>
  </div>
</div>

<footer>Rules for the math &bull; AI for the language &bull; human for the decisions
&nbsp;|&nbsp; FinRecon Copilot</footer>
</div></body></html>"""


def main() -> int:
    OUT.write_text(build_html(), encoding="utf-8")
    print(f"[dashboard] wrote {OUT}")
    print(f"[dashboard] open it in a browser:  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
