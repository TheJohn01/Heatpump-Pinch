"""Interactive charts (Altair / Vega-Lite) for the front end.

Each function takes data already computed by the toolkit and returns an
``alt.Chart``: hover shows the values, the mouse wheel zooms, drag pans
(``.interactive()``), and the chart menu exports PNG or SVG. The static
Matplotlib figures in ``pinch.plotting`` remain the ones written to files for
the dissertation.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd

from pinch.curves import composite_curve
from pinch.problem_table_algorithm import ProblemTable
from pinch.streams import StreamSet

HOT = "#C0392B"
COLD = "#2471A3"
INK = "#1F2A30"
GREY = "#7F8C8D"


def composite_curves_chart(streams: StreamSet, table: ProblemTable, height: int = 320) -> alt.Chart:
    """Shifted hot and cold composite curves (cold offset by Q̇c,min)."""
    u = table.energy_unit
    Hh, Th = composite_curve(streams, "hot", shifted=True)
    Hc, Tc = composite_curve(streams, "cold", shifted=True, H_offset=table.Qc_min)
    df = pd.concat([pd.DataFrame({"H": Hh, "T": Th, "curve": "Hot composite", "i": np.arange(len(Hh))}),
                    pd.DataFrame({"H": Hc, "T": Tc, "curve": "Cold composite", "i": np.arange(len(Hc))})])
    lines = alt.Chart(df).mark_line(point=alt.OverlayMarkDef(size=25)).encode(
        x=alt.X("H:Q", title=f"Enthalpy, H [{u}]"), y=alt.Y("T:Q", title="Shifted temperature, T* [°C]"),
        order="i:Q",
        color=alt.Color("curve:N", scale=alt.Scale(domain=["Hot composite", "Cold composite"], range=[HOT, COLD]),
                        legend=alt.Legend(title=None, orient="bottom-right")),
        tooltip=[alt.Tooltip("curve:N"), alt.Tooltip("H:Q", format=".3f"), alt.Tooltip("T:Q", format=".1f", title="T*")])
    return (lines + _pinch_rules(table)).properties(height=height, title="Shifted composite curves").interactive()


def _pinch_rules(table: ProblemTable):
    if not table.pinch_T_star_C:
        return alt.Chart(pd.DataFrame({"T": []})).mark_rule()
    df = pd.DataFrame({"T": list(table.pinch_T_star_C), "label": [f"Pinch T* = {t:g} °C" for t in table.pinch_T_star_C]})
    return alt.Chart(df).mark_rule(color=GREY, strokeDash=[4, 4]).encode(y="T:Q", tooltip=["label:N"])


def gcc_chart(table: ProblemTable, units=(), height: int = 340) -> alt.Chart:
    """Grand Composite Curve, optionally with heat pump sink (red) and source (blue) profiles."""
    u = table.energy_unit
    H, T = table.cascade_feasible, table.T_star_C
    gcc = pd.DataFrame({"H": H, "T": T, "i": np.arange(len(H))})
    layers = [alt.Chart(gcc).mark_line(color=INK, point=alt.OverlayMarkDef(size=25, color=INK)).encode(
        x=alt.X("H:Q", title=f"Net heat flow, H [{u}]"), y=alt.Y("T:Q", title="Shifted temperature, T* [°C]"),
        order="i:Q", tooltip=[alt.Tooltip("H:Q", format=".3f"), alt.Tooltip("T:Q", format=".1f", title="T*")])]
    rows, H0 = [], 0.0
    for unit in sorted(units, key=lambda x: x.T_sink_out_C):
        for k, (h, t) in enumerate([(H0, unit.T_sink_in_C), (H0 + unit.Q_sink, unit.T_sink_out_C)]):
            rows.append({"H": h, "T": t, "seg": f"{unit.name} sink", "kind": "Heat pump sink", "k": k,
                         "duty": unit.Q_sink, "COP": unit.COP})
        H0 += unit.Q_sink
    H0 = 0.0
    for unit in sorted([x for x in units if x.has_source], key=lambda x: x.T_source_out_C):
        for k, (h, t) in enumerate([(H0, unit.T_source_in_C), (H0 + unit.Q_source, unit.T_source_out_C)]):
            rows.append({"H": h, "T": t, "seg": f"{unit.name} source", "kind": "Heat pump source", "k": k,
                         "duty": unit.Q_source, "COP": unit.COP})
        H0 += unit.Q_source
    if rows:
        seg = pd.DataFrame(rows)
        layers.append(alt.Chart(seg).mark_line(strokeWidth=4).encode(
            x="H:Q", y="T:Q", detail="seg:N", order="k:Q",
            color=alt.Color("kind:N", scale=alt.Scale(domain=["Heat pump sink", "Heat pump source"], range=[HOT, COLD]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=[alt.Tooltip("seg:N", title="unit"), alt.Tooltip("duty:Q", format=".3f"),
                     alt.Tooltip("COP:Q", format=".2f"), alt.Tooltip("T:Q", format=".1f", title="T [°C]")]))
    layers.append(_pinch_rules(table))
    title = "Grand Composite Curve" + (" with heat pumps" if rows else "")
    return alt.layer(*layers).properties(height=height, title=title).interactive()


def supertargeting_chart(df: pd.DataFrame, height: int = 320) -> alt.Chart:
    """Total annual cost vs ΔTmin for each cost law (table 'supertargeting')."""
    d = df.reset_index(drop=True).copy()
    d["TAC_kEUR"] = d["TAC_EUR"] / 1e3
    base = alt.Chart(d).encode(
        x=alt.X("dTmin_K:Q", title="ΔTmin [K]", scale=alt.Scale(type="log")),
        y=alt.Y("TAC_kEUR:Q", title="Total annual cost [k€/year]", scale=alt.Scale(zero=False)),
        color=alt.Color("cost_law:N", legend=alt.Legend(title="Cost law", orient="right", labelLimit=260)),
        tooltip=[alt.Tooltip("cost_law:N"), alt.Tooltip("dTmin_K:Q", format=".2f"), alt.Tooltip("TAC_kEUR:Q", format=",.1f"),
                 alt.Tooltip("area_m2:Q", format=",.0f"), alt.Tooltip("Qh_min:Q", format=",.0f", title="Q̇h,min [kW]")])
    return (base.mark_line() + base.mark_point(size=18)).properties(height=height, title="ΔTmin supertargeting").interactive()


def electrification_chart(df: pd.DataFrame, threshold: float, x: str = "fraction_of_Qh_min",
                          x_title: str = "Share of Q̇h,min supplied by heat pumps [%]", scale: float = 100,
                          height: int = 300) -> alt.Chart:
    """Payback (left axis) and NPV (right axis) along the electrification curve."""
    d = df.copy()
    d["x"] = d[x] * scale
    d["payback"] = d["payback_years"].replace([np.inf, -np.inf], np.nan).clip(upper=3 * threshold)
    d["NPV_MEUR"] = d["npv_EUR"] / 1e6
    tt = [alt.Tooltip("x:Q", format=".1f", title="x"), alt.Tooltip("payback:Q", format=".2f", title="payback [y]"),
          alt.Tooltip("NPV_MEUR:Q", format=".3f", title="NPV [M€]")]
    pb = alt.Chart(d).mark_line(color=COLD, strokeWidth=2.5).encode(
        x=alt.X("x:Q", title=x_title), y=alt.Y("payback:Q", title="Simple payback [years]",
                                                axis=alt.Axis(titleColor=COLD)), tooltip=tt)
    thr = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(color=COLD, strokeDash=[3, 3]).encode(y="y:Q")
    npv = alt.Chart(d).mark_line(color=HOT, strokeWidth=2.5).encode(
        x="x:Q", y=alt.Y("NPV_MEUR:Q", title="NPV [M€]", axis=alt.Axis(titleColor=HOT, orient="right")), tooltip=tt)
    zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=HOT, strokeDash=[3, 3]).encode(y="y:Q")
    return alt.layer(alt.layer(pb, thr), alt.layer(npv, zero)).resolve_scale(y="independent").properties(
        height=height, title="Electrification curve").interactive()


def price_ratio_chart(df: pd.DataFrame, current_ratio: float, threshold: float, height: int = 300) -> alt.Chart:
    """Payback and NPV of the full design against the electricity-to-gas price ratio."""
    ch = electrification_chart(df.rename(columns={"ratio": "r"}), threshold, x="r",
                               x_title="Electricity-to-gas price ratio [-]", scale=1.0, height=height)
    rule = alt.Chart(pd.DataFrame({"r": [current_ratio], "label": [f"today {current_ratio:.2f}"]})).mark_rule(
        color=GREY, strokeDash=[6, 3]).encode(x="r:Q", tooltip=["label:N"])
    return alt.layer(ch, rule).properties(title="Full design against the price ratio")


def retrofit_charts(options: pd.DataFrame, band_px: int = 34) -> tuple[alt.Chart, alt.Chart]:
    """(gas reduction, payback) bar charts per retrofit option, to place side by side."""
    d = options.reset_index(drop=True).copy()
    d["gas_pct"] = d["gas_reduction_vs_baseline"] * 100
    d["payback"] = d["payback_years"].replace([np.inf], np.nan)
    tt = ["option:N", alt.Tooltip("gas_pct:Q", format=".1f", title="gas reduction [%]"),
          alt.Tooltip("payback:Q", format=".2f", title="payback [y]"), alt.Tooltip("npv_EUR:Q", format=",.0f", title="NPV [€]"),
          alt.Tooltip("capex_EUR:Q", format=",.0f", title="CAPEX [€]")]
    y = alt.Y("option:N", title=None, sort=None, axis=alt.Axis(labelLimit=260, labelOverlap=False))
    a = alt.Chart(d).mark_bar(color=COLD).encode(x=alt.X("gas_pct:Q", title="Gas reduction vs existing site [%]"),
                                                 y=y, tooltip=tt).properties(height=alt.Step(band_px), title="Gas reduction")
    b = alt.Chart(d).mark_bar(color=HOT).encode(x=alt.X("payback:Q", title="Simple payback [years]"),
                                                y=y, tooltip=tt).properties(height=alt.Step(band_px), title="Payback")
    rule = alt.Chart(pd.DataFrame({"x": [5.0]})).mark_rule(color=GREY, strokeDash=[4, 3]).encode(x="x:Q")
    return a, alt.layer(b, rule)


def tornado_chart(rq: pd.DataFrame, height: int | None = None) -> alt.Chart:
    """Break-even ratio of HP1's increment (the unit that answers RQ1) for every sensitivity row, against the
    base case; rows without a value (e.g. no heat pump) are left out."""
    col = "RQ3_ratio_HP1"
    name = str(rq.iloc[0].get("HP1_name", "HP1"))
    base = float(rq.iloc[0][col])
    today = float(rq.iloc[0]["price_ratio"])
    d = rq.iloc[1:].dropna(subset=[col]).reset_index(drop=True).copy()
    d["delta"] = d[col] - base
    d["direction"] = np.where(d["delta"] >= 0, "higher (more competitive)", "lower")
    d["start"], d["end"] = base, d[col]
    order = d.reindex(d["delta"].abs().sort_values(ascending=False).index)["sensitivity"].tolist()
    bars = alt.Chart(d).mark_bar().encode(
        y=alt.Y("sensitivity:N", sort=order, title=None, axis=alt.Axis(labelLimit=380, labelOverlap=False)),
        x=alt.X("start:Q", title=f"Break-even price ratio, {name} increment (NPV = 0)"), x2="end:Q",
        color=alt.Color("direction:N", scale=alt.Scale(domain=["higher (more competitive)", "lower"], range=[COLD, HOT]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["sensitivity:N", alt.Tooltip(f"{col}:Q", format=".2f", title="ratio"),
                 alt.Tooltip("RQ1_HP_gas_share:Q", format=".1%", title="RQ1"), "basis:N"])
    rules = alt.Chart(pd.DataFrame({"x": [base, today], "what": [f"base {base:.2f}", f"today's ratio {today:.2f}"]})).mark_rule(
        strokeDash=[5, 3]).encode(x="x:Q", color=alt.value(INK), tooltip=["what:N"])
    return alt.layer(bars, rules).properties(height=height or alt.Step(24 if len(d) > 4 else 48), title=f"RQ3 sensitivity ({name})")
