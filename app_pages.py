"""Pages of the Streamlit front end (see app.py).

Layout
------
* **Workflow**: a step-by-step wizard following the dissertation method (1
  streams, 2 targets, 3 ΔTmin, 4 heat pumps, 5 retrofit, 6 economics). Steps
  with many inputs use a split workspace: inputs on the left, results on the right.
* **Dashboard**: RQ1-RQ3 on one screen (consolidated sensitivity table, tornado).
* **Sources**: provenance of every input, the assumptions register, downloads.

All calculation is done by the toolkit (``analyse.compute``, ``consolidate_rq``);
this module only collects inputs, keeps them in ``st.session_state`` across
steps and pages, and draws interactive charts (``pinch.charts``).
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
import streamlit as st

from analyse import compute, markdown, write
from pinch import charts, problem_table, with_extra_shift
from pinch.case import SinkLevelSpec, load_case
from pinch.cycle_analysis import load_selected
from pinch.economics import DEFAULTS
from pinch.streams import streams_from_frame

ROOT = Path(__file__).resolve().parent
CASES = {p.stem: p for p in sorted((ROOT / "cases").glob("*.json")) if p.stem != "TEMPLATE"}
UPLOAD = "Upload my own stream table"
H_COLUMN = "h_kW_per_m2K"
STEPS = ["1 Streams", "2 Targets", "3 ΔTmin", "4 Heat pumps", "5 Retrofit", "6 Economics"]
ECON_FIELDS = [  # (key, label, min, max, step, format)
    ("gas_price_EUR_per_kWh", "Gas price [€/kWh, GCV]", 0.001, 1.0, 0.001, "%.4f"),
    ("electricity_price_EUR_per_kWh", "Electricity price [€/kWh]", 0.001, 1.0, 0.001, "%.4f"),
    ("boiler_efficiency", "Boiler efficiency [-, GCV]", 0.5, 1.1, 0.005, "%.3f"),
    ("chiller_cop", "Chiller COP [-] (0 = no refrigeration credit)", 0.0, 12.0, 0.05, "%.2f"),
    ("refrigeration_credit_fraction", "Refrigeration credit fraction [-]", 0.0, 1.0, 0.05, "%.2f"),
    ("co2_price_EUR_per_t", "CO₂ price [€/t]", 0.0, 500.0, 1.0, "%.1f"),
    ("grid_EF_kg_per_kWh", "Grid emission factor [kg/kWh]", 0.0, 1.5, 0.001, "%.3f"),
    ("gas_EF_kg_per_kWh", "Gas emission factor [kg/kWh, GCV]", 0.0, 0.5, 0.001, "%.3f"),
    ("discount_rate", "Discount rate [-]", 0.0, 0.5, 0.005, "%.3f"),
    ("horizon_years", "Horizon [years]", 1, 40, 1, None),
    ("payback_threshold_years", "Payback threshold for RQ1 [years]", 0.5, 30.0, 0.5, "%.1f"),
]
ss = st.session_state


# ================================================================== state
def _econ_default(block: dict, key: str):
    if key in block:
        v = block[key]
        return 0.0 if (key == "chiller_cop" and v is None) else v
    if key == "electricity_price_EUR_per_kWh":
        return DEFAULTS["electricity_to_gas_ratio"][0] * DEFAULTS["gas_price_EUR_per_kWh"][0]
    v = DEFAULTS[key][0]
    return 0.0 if v is None else v


def _levels_frame(levels) -> pd.DataFrame:
    return pd.DataFrame([{"name": lv.name, "T_sink_in_C": str(lv.T_sink_in_C), "T_sink_out_C": str(lv.T_sink_out_C),
                          "T_source_C": lv.T_source_C} for lv in levels])


def load_inputs(choice: str, uploaded: pd.DataFrame | None = None, upload_name: str = "my_site") -> None:
    """(Re)initialise every input from a published case or from an uploaded table."""
    if choice == UPLOAD:
        case = load_case(ROOT / "cases" / "TEMPLATE.json")
        case = replace(case, name=Path(upload_name).stem, description="User-supplied stream table.",
                       reference="User upload", screening={}, provenance={"stream data": "user upload (not verified)"},
                       retrofit=None, cycle_screening=None, eta_lorenz_sensitivity=())
        streams_df = uploaded
        basis = {"type": "power", "operating_hours_per_year": 8000.0}
    else:
        case = load_case(CASES[choice])
        streams_df = pd.read_csv(case.stream_file)
        basis = case.basis
    for k in [k for k in ss.keys() if str(k).startswith("_w_")]:   # widgets re-read the new values
        del ss[k]
    ss.choice = choice
    ss.base_case = case
    ss.streams_df = streams_df.copy()
    ss.streams_original = streams_df.copy()
    ss.streams_ver = ss.get("streams_ver", 0) + 1
    ss.levels_df = _levels_frame(case.sink_levels)
    ss.levels_original = ss.levels_df.copy()
    ss.levels_ver = ss.get("levels_ver", 0) + 1
    ss.eta = float(case.eta_lorenz)
    ss.source_T = float(case.source_T_C)
    ss.ambient = float(case.ambient_T_C if case.ambient_T_C is not None else 15.0)
    ss.basis = dict(basis) if basis else None
    eco = dict(case.economics or {})
    for key, *_ in ECON_FIELDS:
        ss[f"econ_{key}"] = _econ_default(eco, key)
    ss.run_area = bool(case.area_targeting) or choice == UPLOAD
    ss.rq_table = None
    ss.scalar_original = _scalars()


def _scalars() -> dict:
    keys = ["eta", "source_T", "ambient", "run_area"] + [f"econ_{k}" for k, *_ in ECON_FIELDS]
    return {k: ss[k] for k in keys} | {"basis": json.dumps(ss.basis, sort_keys=True)}


def init_state() -> None:
    if "choice" not in ss:
        load_inputs("brewery_padulles2026" if "brewery_padulles2026" in CASES else next(iter(CASES)))
    ss.setdefault("step", STEPS[0])
    if "step_ctl" not in ss:
        ss.step_ctl = ss.step


def _copy(widget_key: str, name: str) -> None:
    ss[name] = ss[widget_key]


def bind(widget, label: str, name: str, *args, **kw):
    """A widget whose value survives when it is not rendered (other step or page).

    The value lives in ss[name]; the widget has its own key, initialised from
    it, and copies changes back through a callback (callbacks run before the
    script, so the change is never overwritten).
    """
    k = f"_w_{name}"
    if k not in ss:
        ss[k] = ss[name]
    return widget(label, *args, key=k, on_change=_copy, args=(k, name), **kw)


def _goto(step: str) -> None:
    ss.step = step
    ss.step_ctl = step


def _step_changed() -> None:
    if ss.step_ctl:
        ss.step = ss.step_ctl
    else:                       # clicking the selected step again clears it: keep the step
        ss.step_ctl = ss.step


def _editor(df_name: str, ver_name: str, **kw) -> None:
    """Editable table stored in session state; edits become the new base table."""
    ed = st.data_editor(ss[df_name], key=f"ed_{df_name}_{ss[ver_name]}", width="stretch", **kw)
    if not ed.equals(ss[df_name]):
        ss[df_name] = ed.reset_index(drop=True)
        ss[ver_name] += 1
        st.rerun()


# ================================================================== case and results
def _temperature(value, field: str, level: str):
    text = str(value).strip()
    if text == "gcc_max":
        return text
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"sink level '{level}': {field} must be a number or 'gcc_max' (got '{text}')") from None


def build_case():
    """Case and stream set from the current inputs (raises ValueError with a readable message)."""
    case = ss.base_case
    df = ss.streams_df
    streams = streams_from_frame(df.drop(columns=[H_COLUMN], errors="ignore"), source=f"{case.name}.csv")
    levels = []
    for row in ss.levels_df.dropna(subset=["name"]).itertuples(index=False):
        src = None if pd.isna(row.T_source_C) else float(row.T_source_C)
        levels.append(SinkLevelSpec(str(row.name), _temperature(row.T_sink_in_C, "T_sink_in_C", row.name),
                                    _temperature(row.T_sink_out_C, "T_sink_out_C", row.name), src))
    if not levels:
        raise ValueError("give at least one heat pump sink level")
    eco = dict(case.economics or {})
    for key, *_ in ECON_FIELDS:
        v = ss[f"econ_{key}"]
        eco[key] = (None if (key == "chiller_cop" and float(v) <= 0) else (int(v) if key == "horizon_years" else float(v)))
    basis = ss.basis
    if basis and basis["type"] == "power":
        eco["operating_hours_per_year"] = basis["operating_hours_per_year"]
    area = case.area_targeting if ss.run_area else None
    if ss.run_area and ss.choice == UPLOAD:
        area = None
        if H_COLUMN in df.columns:
            area = {"film_coefficients_kW_per_m2K": dict(zip(df["stream"].astype(str), df[H_COLUMN].astype(float))),
                    "film_coefficients_source": "user upload", "cost_law": None,
                    "specific_area_cost_sweep_EUR_per_m2": [250, 500, 1000, 2000]}
    run_case = replace(case, eta_lorenz=float(ss.eta), source_T_C=float(ss.source_T), ambient_T_C=float(ss.ambient),
                       sink_levels=tuple(levels), basis=basis, economics=eco if basis else None, area_targeting=area)
    return run_case, streams


def _unedited() -> bool:
    """Same streams, sink levels and source as the published case (cycle screening still applies)."""
    return (ss.choice != UPLOAD and ss.streams_df.equals(ss.streams_original)
            and ss.levels_df.equals(ss.levels_original) and ss.source_T == ss.base_case.source_T_C)


def _all_defaults() -> bool:
    """Every input as published (saved outputs such as the consolidated table apply)."""
    return _unedited() and _scalars() == ss.scalar_original


def _key(case, streams_df) -> str:
    payload = json.dumps({"case": repr(case), "streams": streams_df.to_csv(index=False), "unedited": _unedited()},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@st.cache_resource(max_entries=8, show_spinner=False)
def _compute(key: str, _case, _streams, _selected):
    return compute(_case, _streams, cycle_selected=_selected)


@st.cache_data(max_entries=8, show_spinner=False)
def _zip(key: str, _result, name: str) -> bytes:
    """All files as the command line writes them (figures are released after writing)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / name
        write(_result, out)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.iterdir()):
                z.write(f, f"{name}/{f.name}")
    return buf.getvalue()


def results():
    """(case, streams, summary, tables, key, Outputs) for the current inputs, or None after showing the error."""
    try:
        case, streams = build_case()
        selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json") if _unedited() else None
        key = _key(case, ss.streams_df)
        with st.spinner("Computing..."):
            res = _compute(key, case, streams, selected)
        return case, streams, res.summary, res.tables, key, res
    except ValueError as exc:
        st.error(f"Input problem: {exc}")
    except Exception as exc:  # keep the app alive, show the message
        st.error(f"The analysis failed: {type(exc).__name__}: {exc}")
    return None


@dataclass
class _Unit:  # light view of a heat pump row, for the GCC chart
    name: str
    T_sink_in_C: float
    T_sink_out_C: float
    T_source_in_C: float
    T_source_out_C: float
    Q_sink: float
    Q_source: float
    COP: float
    has_source: bool = True


def _units(tables, unit: str) -> list[_Unit]:
    df = tables.get("heat_pump_design")
    if df is None or not len(df):
        return []
    return [_Unit(r["unit"], r["T_sink_in_C"], r["T_sink_out_C"], r["T_source_C"], r["T_source_C"],
                  r[f"Q_sink_{unit}"], r[f"Q_source_{unit}"], r["COP"]) for _, r in df.iterrows()]


def _chart(ch) -> None:
    st.altair_chart(ch, width="stretch")


# ================================================================== workflow (wizard)
def workflow_page() -> None:
    init_state()
    st.title("Process-heat electrification")
    st.caption(f"Case: **{ss.base_case.name}** · {ss.base_case.reference}")
    st.segmented_control("Step", STEPS, key="step_ctl", on_change=_step_changed, label_visibility="collapsed")
    st.progress((STEPS.index(ss.step) + 1) / len(STEPS))
    {STEPS[0]: _step_streams, STEPS[1]: _step_targets, STEPS[2]: _step_dtmin, STEPS[3]: _step_heat_pumps,
     STEPS[4]: _step_retrofit, STEPS[5]: _step_economics}[ss.step]()
    i = STEPS.index(ss.step)
    c = st.columns([1, 6, 1])
    if i > 0:
        c[0].button("← Back", width="stretch", on_click=_goto, args=(STEPS[i - 1],))
    if i < len(STEPS) - 1:
        c[2].button("Next →", type="primary", width="stretch", on_click=_goto, args=(STEPS[i + 1],))


def _step_streams() -> None:
    left, right = st.columns([1, 2.4], gap="large")
    with left, st.container(border=True):
        st.subheader("Process")
        options = list(CASES) + [UPLOAD]
        choice = st.selectbox("Case", options, index=options.index(ss.choice))
        if choice != ss.choice and choice != UPLOAD:
            load_inputs(choice)
            st.rerun()
        if choice == UPLOAD:
            f = st.file_uploader("Stream table (CSV)", type="csv",
                                 help="Columns: stream, type (hot/cold), T_in_C, T_out_C, dT_shift_K and one of "
                                      f"Q_<unit> or CP_<unit>. Optional: {H_COLUMN} for ΔTmin supertargeting.")
            if f is not None and (ss.choice != UPLOAD or ss.get("upload_name") != f.name):
                try:
                    df = pd.read_csv(f)
                except Exception as exc:
                    st.error(f"Could not read the CSV: {exc}")
                    return
                ss.upload_name = f.name
                load_inputs(UPLOAD, df, f.name)
                st.rerun()
            if ss.choice != UPLOAD:
                st.info("Upload a CSV to replace the published case.")
        st.subheader("Annual basis")
        b = ss.basis
        if b and b["type"] == "per_product":
            v = st.number_input(f"Production [{b['production_unit']}/year]", min_value=1.0,
                                value=float(b["production_per_year"]))
            ss.basis = {**b, "production_per_year": v}
        elif b:
            v = st.number_input("Operating hours [h/year]", 1.0, 8784.0, float(b["operating_hours_per_year"]))
            ss.basis = {**b, "operating_hours_per_year": v}
        else:
            st.caption("No annual basis: results stay in the stream-data unit.")
    with right:
        st.subheader("Stream table (editable)")
        st.caption("Each change recomputes every step. Latent loads over 1 K. 'Amb.' streams use 15 °C.")
        _editor("streams_df", "streams_ver", num_rows="dynamic")
        r = results()
        if r:
            s = r[2]
            t = s["targets"]
            c = st.columns(3)
            c[0].metric(f"Hot streams [{s['energy_unit']}]", f"{t['Q_hot_total']:.4g}", border=True)
            c[1].metric(f"Cold streams [{s['energy_unit']}]", f"{t['Q_cold_total']:.4g}", border=True)
            c[2].metric("Net surplus (hot − cold)", f"{t['Q_hot_total'] - t['Q_cold_total']:+.4g}", border=True)


def _step_targets() -> None:
    r = results()
    if not r:
        return
    case, streams, s, tables, *_ = r
    shifted = with_extra_shift(streams, case.extra_shift_K)
    table = problem_table(shifted)
    t, u = s["targets"], s["energy_unit"]
    c = st.columns(4)
    c[0].metric(f"Q̇h,min [{u}]", f"{t['Qh_min']:.4g}", border=True)
    c[1].metric(f"Q̇c,min [{u}]", f"{t['Qc_min']:.4g}", border=True)
    c[2].metric(f"Heat recovery [{u}]", f"{t['heat_recovery']:.4g}", border=True)
    c[3].metric("Pinch T* [°C]", ", ".join(f"{p:g}" for p in t["pinch_T_star_C"]) or "threshold", border=True)
    a, b = st.columns(2)
    with a:
        _chart(charts.composite_curves_chart(shifted, table))
    with b:
        _chart(charts.gcc_chart(table))
    with st.expander("Problem table (heat cascade)"):
        st.dataframe(tables["problem_table"], width="stretch")


def _step_dtmin() -> None:
    left, right = st.columns([1, 2.4], gap="large")
    with left, st.container(border=True):
        st.subheader("Supertargeting")
        bind(st.toggle, "Run ΔTmin supertargeting (RQ2)", "run_area")
        st.caption("Cost laws and film coefficients come from the case file (Sources page).")
    with right:
        r = results()
        if not r:
            return
        at = r[2].get("area_targeting", {})
        if not at or "skipped" in at:
            st.info(f"Supertargeting not run: {at.get('skipped', 'switched off')}.")
            return
        _chart(charts.supertargeting_chart(r[3]["supertargeting"]))
        st.dataframe(pd.DataFrame(at["RQ2"]).drop(columns=["a", "b", "c"], errors="ignore"), width="stretch")
        st.caption(f"Hot utility {at['hot_utility_cost_EUR_per_kW_year']} €/kW·year; cold utility "
                   f"{at['cold_utility_cost_EUR_per_kW_year']:.1f} €/kW·year. Optimum ΔTmin is a lower bound "
                   "(pumping, fouling and batch timing are not modelled).")


def _step_heat_pumps() -> None:
    left, right = st.columns([1.35, 2.2], gap="large")
    with left, st.container(border=True, height=640):
        st.subheader("Heat pumps")
        bind(st.slider, "Lorenz efficiency η_L [-]", "eta", 0.30, 0.80, step=0.01,
             help="Padullés et al. (2026): 0.55; DEA-implied 0.45-0.52; cycle model per unit on the right.")
        bind(st.number_input, "Default source temperature [°C, T*]", "source_T", step=1.0)
        bind(st.number_input, "Ambient temperature [°C]", "ambient", step=1.0)
        st.markdown("**Sink levels**")
        st.caption("°C on the T* axis; 'gcc_max' = isothermal sink at the top of the GCC.")
        _editor("levels_df", "levels_ver", num_rows="dynamic", hide_index=True,
                column_config={"name": st.column_config.TextColumn("level", width="medium"),
                               "T_sink_in_C": st.column_config.TextColumn("in [°C]", width="small"),
                               "T_sink_out_C": st.column_config.TextColumn("out [°C]", width="small"),
                               "T_source_C": st.column_config.NumberColumn("source [°C]", width="small")})
    with right:
        r = results()
        if not r:
            return
        case, streams, s, tables, *_ = r
        d, u = s["heat_pump_design"], s["energy_unit"]
        c = st.columns(4)
        c[0].metric(f"Heat delivered [{u}]", f"{d['Q_sink_total']:.4g}", border=True)
        c[1].metric(f"Electricity [{u}]", f"{d['W_total']:.4g}", border=True)
        c[2].metric("System COP", f"{d['COP_system']:.2f}", border=True)
        c[3].metric("Share of Q̇h,min electrified", f"{100 * d['fraction_of_Qh_min_electrified']:.1f} %", border=True)
        for name, w in s["warnings"].items():
            st.warning(f"**{name}**: " + "; ".join(w))
        table = problem_table(with_extra_shift(streams, case.extra_shift_K))
        _chart(charts.gcc_chart(table, _units(tables, u)))
        st.dataframe(tables["heat_pump_design"], width="stretch")
        cb = s.get("cycle_based_design")
        if cb:
            st.markdown("**Working-fluid check (step 4b)**: best practical cycle per unit")
            st.dataframe(pd.DataFrame([{"unit": n, **v} for n, v in cb["units"].items()]), width="stretch")
        elif ss.choice != UPLOAD:
            st.caption("Working-fluid check applies to the unedited published case (run screen_cycles.py for others).")


def _step_retrofit() -> None:
    r = results()
    if not r:
        return
    rf = r[2].get("retrofit")
    if not rf or "skipped" in rf:
        st.info(f"No existing network for this case: {rf['skipped'] if rf else 'add a retrofit block and a network file'}.")
        return
    b, u = rf["baseline"], r[2]["energy_unit"]
    st.subheader(f"Existing network: {b['network']}")
    c = st.columns(4)
    c[0].metric(f"Q̇h of the network [{u}]", f"{b['Qh']:.4g}", delta=f"{b['energy_gap']:+.3g} vs target",
                delta_color="inverse", border=True)
    c[1].metric("Cooling above the pinch", f"{b['coolers_above_pinch']:.3g}", border=True)
    c[2].metric("Cross-pinch in exchangers", f"{b['cross_pinch_in_matches']:.3g}", border=True)
    c[3].metric("Refrigeration below ambient", f"{b['refrigeration_below_ambient']:.3g}", border=True)
    g, pb = charts.retrofit_charts(pd.DataFrame(rf["options"]))
    a, b = st.columns(2)
    with a:
        _chart(g)
    with b:
        _chart(pb)
    st.dataframe(pd.DataFrame(rf["options"]), width="stretch")
    tables = r[3]
    with st.expander("Networks: matches, heaters, coolers"):
        for k in sorted(t for t in tables if t.startswith("retrofit_n")):
            st.caption(k.removeprefix("retrofit_"))
            st.dataframe(tables[k], width="stretch")
    if "retrofit_new_equipment" in tables:
        with st.expander("New equipment (exchangers and storage)"):
            st.dataframe(tables["retrofit_new_equipment"], width="stretch")


def _step_economics() -> None:
    left, right = st.columns([1, 2.4], gap="large")
    with left, st.container(border=True, height=700):
        st.subheader("Economic inputs")
        for key, label, lo, hi, step, fmt in ECON_FIELDS:
            kw = {"format": fmt} if fmt else {}
            if key == "horizon_years":
                bind(st.number_input, label, f"econ_{key}", int(lo), int(hi), step=int(step))
            else:
                bind(st.number_input, label, f"econ_{key}", float(lo), float(hi), step=float(step), **kw)
            if key == "electricity_price_EUR_per_kWh":
                st.caption(f"Electricity-to-gas ratio: **{ss['econ_electricity_price_EUR_per_kWh'] / ss['econ_gas_price_EUR_per_kWh']:.2f}**")
    with right:
        r = results()
        if not r:
            return
        ec = r[2].get("economics", {})
        if not ec or "skipped" in ec:
            st.info(f"Economics not run: {ec.get('skipped', 'no annual basis')}.")
            return
        tables = r[3]
        r1, r3, full = ec["RQ1"], ec["RQ3"], ec["results"]["full design (heat recovery installed)"]
        c = st.columns(4)
        c[0].metric(f"RQ1: share, payback ≤ {r1['threshold_years']:g} y", f"{100 * r1['max_fraction_with_payback_below_threshold']:.1f} %", border=True)
        c[1].metric("RQ3: break-even ratio", f"{r3['break_even_ratio_NPV']:.2f}",
                    delta=f"{r3['break_even_ratio_NPV'] - r3['ratio_used']:+.2f} vs today", delta_color="off", border=True)
        c[2].metric("Full design: payback", f"{full['payback_years']:.1f} y", border=True)
        c[3].metric(f"Full design: NPV{int(ss['econ_horizon_years'])}", f"{full['npv_EUR'] / 1e6:+.2f} M€", border=True)
        st.caption("Against the site with heat recovery at target. The Retrofit step compares with the existing network.")
        thr = float(ss["econ_payback_threshold_years"])
        a, b = st.columns(2)
        with a:
            _chart(charts.electrification_chart(tables["electrification_curve"], thr))
        with b:
            _chart(charts.price_ratio_chart(tables["price_ratio_sweep"], ec["price_ratio"], thr))
        if "scenarios" in tables:
            with st.expander("Scenarios from the case file"):
                st.dataframe(tables["scenarios"], width="stretch")
        if "eta_lorenz_sensitivity" in tables:
            with st.expander("Lorenz-efficiency sensitivity (heat pumps re-sized)"):
                st.dataframe(tables["eta_lorenz_sensitivity"], width="stretch")


# ================================================================== dashboard
@st.cache_resource(max_entries=4, show_spinner=False)
def _consolidate(key: str, _case, _streams, _selected) -> pd.DataFrame:
    from consolidate_rq import consolidate_case
    return consolidate_case(_case, _streams, _selected)


def dashboard_page() -> None:
    init_state()
    st.title("Research questions at a glance")
    r = results()
    if not r:
        return
    case, streams, s, tables, *_ = r
    saved = ROOT / "outputs" / case.name / "rq_consolidated.csv"
    head = st.columns([4, 1.4], vertical_alignment="center")
    if ss.rq_table is not None and ss.rq_table[0] == _key(case, ss.streams_df):
        rq, origin = ss.rq_table[1], "current inputs"
    elif _all_defaults() and saved.exists():
        rq, origin = pd.read_csv(saved), "published case, saved run"
    else:
        rq, origin = None, ""
    if case.retrofit and case.basis is not None:
        if head[1].button("Recompute table (≈15 s)", type="primary", width="stretch"):
            selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json") if _unedited() else None
            with st.spinner("Running every sensitivity..."):
                rq = _consolidate(_key(case, ss.streams_df), case, streams, selected)
            ss.rq_table = (_key(case, ss.streams_df), rq)
            origin = "current inputs"
    head[0].caption(f"Consolidated sensitivities: {origin or 'not computed for these inputs'}")
    if rq is None:
        st.info("The consolidated table needs an existing-network (retrofit) block; press the button to compute it "
                "for the current inputs." if case.retrofit else "This case has no retrofit block, so the "
                "consolidated RQ table is not available.")
        return
    b = rq.iloc[0]
    c = st.columns(4)
    c[0].metric("RQ1: gas share, payback ≤ 5 y", f"{100 * b['RQ1_gas_share']:.1f} %", border=True,
                help=f"{b['RQ1_option']} · payback {b['RQ1_payback_y']} y")
    c[1].metric("Warm-water heat pump alone", f"{b['warm_water_HP_incremental_payback_y']} y", border=True,
                help="payback of its increment over the heat-recovery retrofit")
    c[2].metric("RQ2: ΔTmin,opt", f"{b['RQ2_dTmin_opt_K']:g} K", border=True)
    c[3].metric("RQ3: break-even ratio (full / WW HP)",
                f"{b['RQ3_ratio_full_electrification']:.2f} / {b['RQ3_ratio_warm_water_HP_only']:.2f}",
                delta=f"today {b['price_ratio']:.2f}", delta_color="off", border=True)
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        _chart(charts.tornado_chart(rq))
    with right:
        rf = s.get("retrofit")
        if rf and "skipped" not in rf:
            g, pb = charts.retrofit_charts(pd.DataFrame(rf["options"]), band_px=26)
            _chart(g)
            _chart(pb)
    st.dataframe(rq, width="stretch", hide_index=True)


# ================================================================== sources
def sources_page() -> None:
    init_state()
    st.title("Sources, assumptions and downloads")
    r = results()
    if not r:
        return
    case, _, s, _, key, res = r
    a, b = st.columns(2, gap="large")
    with a:
        st.subheader("Provenance (case file)")
        for k, v in s["provenance"].items():
            st.markdown(f"- **{k}**: {v}")
        ec = s.get("economics", {})
        if ec and "skipped" not in ec:
            st.subheader("Economic inputs")
            for k, v in {**ec.get("default_sources", {}), **ec.get("case_sources", {})}.items():
                st.markdown(f"- **{k}**: {v}")
            st.caption("Values changed in the app keep the case-file note above; cite your own source for them.")
    with b:
        st.subheader("Downloads")
        st.download_button("All results (zip)", _zip(key, res, case.name), file_name=f"{case.name}_results.zip",
                           mime="application/zip", width="stretch")
        st.download_button("Summary (Markdown)", markdown(s), file_name=f"{case.name}_summary.md", width="stretch")
        st.download_button("Summary (JSON)", json.dumps(s, indent=2, ensure_ascii=False, default=str),
                           file_name=f"{case.name}_summary.json", width="stretch")
        reg = ROOT / "ASSUMPTIONS.md"
        if reg.exists() and case.name.startswith("brewery"):
            st.subheader("Assumptions register")
            with st.container(height=520, border=True):
                text = reg.read_text(encoding="utf-8").split("\n", 1)[1]   # drop the file's own title
                st.markdown(text)
