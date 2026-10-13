"""Interactive front end for the heat pump pinch toolkit (Streamlit).

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

The app does no calculation of its own: it builds a ``Case`` and a stream table
from the inputs on the page, calls ``analyse.compute`` (the same function the
command line and the tests use) and displays the returned tables and figures.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from analyse import compute, markdown, write
from pinch.case import SinkLevelSpec, load_case
from pinch.cycle_analysis import load_selected
from pinch.economics import DEFAULTS
from pinch.streams import streams_from_frame

ROOT = Path(__file__).resolve().parent
CASES = {p.stem: p for p in sorted((ROOT / "cases").glob("*.json")) if p.stem != "TEMPLATE"}
UPLOAD = "Upload my own stream table"
H_COLUMN = "h_kW_per_m2K"  # optional column in an uploaded table: film coefficient for RQ2

st.set_page_config(page_title="Heat pump pinch analysis", layout="wide")


# ------------------------------------------------------------------ helpers
def _econ(block: dict, key: str) -> float:
    """Value from the case's economics block, else the sourced default."""
    if key in block:
        return float(block[key])
    if key == "electricity_price_EUR_per_kWh":
        return DEFAULTS["electricity_to_gas_ratio"][0] * DEFAULTS["gas_price_EUR_per_kWh"][0]
    return float(DEFAULTS[key][0])


def _levels_frame(levels) -> pd.DataFrame:
    return pd.DataFrame([{"name": lv.name, "T_sink_in_C": str(lv.T_sink_in_C), "T_sink_out_C": str(lv.T_sink_out_C),
                          "T_source_C": lv.T_source_C} for lv in levels])


def _temperature(value, field_name: str, level: str) -> float | str:
    text = str(value).strip()
    if text == "gcc_max":
        return text
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"sink level '{level}': {field_name} must be a number or 'gcc_max' (got '{text}')") from None


def _levels_from_frame(df: pd.DataFrame) -> tuple[SinkLevelSpec, ...]:
    levels = []
    for row in df.dropna(subset=["name"]).itertuples(index=False):
        src = None if pd.isna(row.T_source_C) else float(row.T_source_C)
        levels.append(SinkLevelSpec(str(row.name), _temperature(row.T_sink_in_C, "T_sink_in_C", row.name),
                                    _temperature(row.T_sink_out_C, "T_sink_out_C", row.name), src))
    if not levels:
        raise ValueError("give at least one heat pump sink level")
    return tuple(levels)


def _show(fig) -> None:
    st.pyplot(fig, clear_figure=False)  # kept open: the zip download saves it again


def _zip_outputs(result, case_name: str) -> bytes:
    """All tables, figures and summaries, as written by the command line, in one zip."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / case_name
        write(result, out)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.iterdir()):
                z.write(f, f"{case_name}/{f.name}")
    return buffer.getvalue()


# ------------------------------------------------------------------ inputs
st.title("Process-heat electrification: pinch analysis and heat pumps")
st.caption("Energy targets, GCC-based heat pump sizing, economics (RQ1, RQ3) and ΔTmin supertargeting (RQ2). "
           "Every default carries its source; check the Sources tab before using a number.")

with st.sidebar:
    choice = st.selectbox("Case", list(CASES) + [UPLOAD])
    if choice == UPLOAD:
        case = load_case(ROOT / "cases" / "TEMPLATE.json")
        file = st.file_uploader("Stream table (CSV)", type="csv",
                                help="Columns: stream, type (hot/cold), T_in_C, T_out_C, dT_shift_K and one of "
                                     "Q_<unit> or CP_<unit> (e.g. Q_kW, CP_kW_per_K). Optional: "
                                     f"{H_COLUMN} for ΔTmin supertargeting.")
        if file is None:
            st.info("Upload a CSV to start, or pick a published case.")
            st.stop()
        try:
            streams_df = pd.read_csv(file)
        except Exception as exc:  # unreadable file: say so, do not crash
            st.error(f"Could not read the CSV: {exc}")
            st.stop()
        case = replace(case, name=Path(file.name).stem, description="User-supplied stream table.",
                       reference="User upload", screening={},
                       provenance={"stream data": "user upload (not verified)"})
    else:
        case = load_case(CASES[choice])
        streams_df = pd.read_csv(case.stream_file)

    st.header("Heat pumps")
    eta = st.slider("Lorenz efficiency η_L [-]", 0.30, 0.80, float(case.eta_lorenz), 0.01,
                    help="Padullés et al. (2026): 0.55; DEA-implied 0.45–0.52; Andersen et al. (2024) fit up to ~0.63.")
    source_T = st.number_input("Default source temperature [°C, T* axis]", value=float(case.source_T_C), step=1.0)
    ambient = st.number_input("Ambient temperature [°C]", value=float(case.ambient_T_C or 15.0), step=1.0)

    st.header("Annual basis")
    basis = case.basis
    if choice == UPLOAD:
        kind = st.radio("Loads are", ["power (kW, MW)", "per product (e.g. kWh/t)", "no basis"], index=0)
        if kind.startswith("power"):
            basis = {"type": "power", "operating_hours_per_year": st.number_input("Operating hours [h/year]", 1.0, 8784.0, 8000.0)}
        elif kind.startswith("per product"):
            basis = {"type": "per_product",
                     "production_per_year": st.number_input("Production per year", min_value=1.0, value=1.0e5),
                     "production_unit": st.text_input("Product unit (must match the CSV unit, e.g. t)", "t")}
        else:
            basis = None
    elif basis and basis["type"] == "per_product":
        basis = {**basis, "production_per_year": st.number_input(
            f"Production [{basis['production_unit']}/year]", min_value=1.0, value=float(basis["production_per_year"]))}
    elif basis:
        st.write(f"Operating hours: {basis['operating_hours_per_year']:.0f} h/year (from the case file)")

    st.header("Economics")
    eco = dict(case.economics or {})
    p_gas = st.number_input("Gas price [EUR/kWh, GCV]", 0.001, 1.0, _econ(eco, "gas_price_EUR_per_kWh"), 0.001, format="%.4f")
    p_el = st.number_input("Electricity price [EUR/kWh]", 0.001, 1.0, _econ(eco, "electricity_price_EUR_per_kWh"), 0.001, format="%.4f")
    st.caption(f"Electricity-to-gas price ratio: **{p_el / p_gas:.2f}**")
    eta_b = st.number_input("Boiler efficiency [-, GCV]", 0.5, 1.1, _econ(eco, "boiler_efficiency"), 0.005, format="%.3f")
    co2_price = st.number_input("CO₂ price [EUR/t]", 0.0, 500.0, _econ(eco, "co2_price_EUR_per_t"), 1.0)
    grid_ef = st.number_input("Grid emission factor [kg/kWh]", 0.0, 1.5, _econ(eco, "grid_EF_kg_per_kWh"), 0.001, format="%.3f")
    gas_ef = st.number_input("Gas emission factor [kg/kWh, GCV]", 0.0, 0.5, _econ(eco, "gas_EF_kg_per_kWh"), 0.001, format="%.3f")
    rate = st.number_input("Discount rate [-]", 0.0, 0.5, _econ(eco, "discount_rate"), 0.005, format="%.3f")
    years = st.number_input("Horizon [years]", 1, 40, int(_econ(eco, "horizon_years")))
    threshold = st.number_input("Payback threshold for RQ1 [years]", 0.5, 30.0, _econ(eco, "payback_threshold_years"), 0.5)
    run_area = st.checkbox("ΔTmin supertargeting (RQ2)", value=bool(case.area_targeting) or choice == UPLOAD)

st.subheader(f"Case: {case.name}")
st.write(case.description)
st.caption(f"Source: {case.reference}")

with st.expander("Stream table (editable)", expanded=choice == UPLOAD):
    streams_df = st.data_editor(streams_df, num_rows="dynamic", width="stretch", key=f"streams_{case.name}")
with st.expander("Heat pump sink levels (editable)"):
    st.caption("Temperatures in °C on the T* axis; 'gcc_max' = isothermal sink at the top of the GCC. "
               "Leave T_source_C empty to use the default source temperature.")
    levels_df = st.data_editor(_levels_frame(case.sink_levels), num_rows="dynamic", width="stretch",
                               key=f"levels_{case.name}")

# ------------------------------------------------------------------ build the case and run
try:
    streams = streams_from_frame(streams_df.drop(columns=[H_COLUMN], errors="ignore"), source=f"{case.name}.csv")
    eco.update({"gas_price_EUR_per_kWh": p_gas, "electricity_price_EUR_per_kWh": p_el, "boiler_efficiency": eta_b,
                "co2_price_EUR_per_t": co2_price, "grid_EF_kg_per_kWh": grid_ef, "gas_EF_kg_per_kWh": gas_ef,
                "discount_rate": rate, "horizon_years": int(years), "payback_threshold_years": threshold})
    if basis and basis["type"] == "power":
        eco["operating_hours_per_year"] = basis["operating_hours_per_year"]
    area = case.area_targeting if run_area else None
    if run_area and choice == UPLOAD:
        if H_COLUMN in streams_df.columns:
            area = {**(case.area_targeting or {}),
                    "film_coefficients_kW_per_m2K": dict(zip(streams_df["stream"].astype(str), streams_df[H_COLUMN].astype(float))),
                    "film_coefficients_source": "user upload", "cost_law": None,
                    "specific_area_cost_sweep_EUR_per_m2": [250, 500, 1000, 2000]}
        else:
            area = None
            st.info(f"ΔTmin supertargeting needs a '{H_COLUMN}' column in the stream table.")
    run_case = replace(case, eta_lorenz=float(eta), source_T_C=float(source_T), ambient_T_C=float(ambient),
                       sink_levels=_levels_from_frame(levels_df), basis=basis,
                       economics=eco if basis else None, area_targeting=area)
    with st.spinner("Computing..."):
        # step-4b screening results apply only to the unedited published case (same unit temperatures)
        selected = None
        if choice != UPLOAD and source_T == case.source_T_C and levels_df.equals(_levels_frame(case.sink_levels)):
            selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
        result = compute(run_case, streams, cycle_selected=selected)
except ValueError as exc:
    st.error(f"Input problem: {exc}")
    st.stop()
except Exception as exc:  # unexpected: show the message, keep the app alive
    st.error(f"The analysis failed: {type(exc).__name__}: {exc}")
    st.stop()

s = result.summary
u = s["energy_unit"]
t, d = s["targets"], s["heat_pump_design"]
ec, at = s.get("economics", {}), s.get("area_targeting", {})

# ------------------------------------------------------------------ outputs
tab_t, tab_hp, tab_ec, tab_dt, tab_src = st.tabs(
    ["Targets", "Heat pumps", "Economics (RQ1, RQ3)", "ΔTmin (RQ2)", "Sources and downloads"])

with tab_t:
    c = st.columns(4)
    c[0].metric(f"Q̇h,min [{u}]", f"{t['Qh_min']:.4g}")
    c[1].metric(f"Q̇c,min [{u}]", f"{t['Qc_min']:.4g}")
    c[2].metric(f"Heat recovery [{u}]", f"{t['heat_recovery']:.4g}")
    c[3].metric("Pinch T* [°C]", ", ".join(f"{p:g}" for p in t["pinch_T_star_C"]) or "threshold")
    left, right = st.columns(2)
    with left:
        _show(result.figures["composite_curves"])
    with right:
        _show(result.figures["gcc"])
    st.dataframe(result.tables["problem_table"], width="stretch")

with tab_hp:
    c = st.columns(4)
    c[0].metric(f"Heat delivered [{u}]", f"{d['Q_sink_total']:.4g}")
    c[1].metric(f"Electricity [{u}]", f"{d['W_total']:.4g}")
    c[2].metric("System COP [-]", f"{d['COP_system']:.2f}")
    c[3].metric("Share of Q̇h,min electrified", f"{100 * d['fraction_of_Qh_min_electrified']:.1f} %")
    for name, warnings in s["warnings"].items():
        st.warning(f"**{name}**: " + "; ".join(warnings))
    _show(result.figures["gcc_heat_pumps"])
    st.dataframe(result.tables["heat_pump_design"], width="stretch")
    cb = s.get("cycle_based_design")
    if cb:
        st.markdown("**Cycle-based check (step 4b, `screen_cycles.py`)**: best working fluid per unit and the "
                    "Lorenz efficiency it implies, versus the value assumed above")
        st.dataframe(pd.DataFrame([{"unit": n, **v} for n, v in cb["units"].items()]), width="stretch")
        if "economics" in cb:
            e = cb["economics"]
            st.caption(f"With cycle-based COPs: system COP {cb['COP_system']}, full-design payback "
                       f"{e['full_payback_years']} y, NPV {e['full_npv_EUR']:,.0f} EUR, RQ1 "
                       f"{100 * e['RQ1_max_fraction_payback_ok']:.1f} %, RQ3 {e['RQ3_break_even_ratio_NPV']}.")
    elif choice != UPLOAD:
        st.caption("No cycle-based check for these inputs (run screen_cycles.py on the unedited case).")

with tab_ec:
    if not ec or "skipped" in ec:
        st.info(f"Economics not run: {ec.get('skipped', 'no annual basis')}.")
    else:
        r1, r3, full = ec["RQ1"], ec["RQ3"], ec["results"]["full design (heat recovery installed)"]
        c = st.columns(4)
        c[0].metric(f"RQ1: share with payback ≤ {r1['threshold_years']:g} y",
                    f"{100 * r1['max_fraction_with_payback_below_threshold']:.1f} %")
        c[1].metric("RQ1: share with maximum NPV", f"{100 * r1['fraction_with_max_NPV']:.1f} %")
        c[2].metric("RQ3: break-even ratio (NPV = 0)", f"{r3['break_even_ratio_NPV']:.2f}",
                    delta=f"{r3['break_even_ratio_NPV'] - r3['ratio_used']:+.2f} vs current ratio", delta_color="off")
        c[3].metric("Full design: payback [y]", f"{full['payback_years']:.1f}")
        c = st.columns(4)
        c[0].metric("Full design: CAPEX [EUR]", f"{full['capex_EUR']:,.0f}")
        c[1].metric(f"Full design: NPV{years} [EUR]", f"{full['npv_EUR']:,.0f}")
        c[2].metric("CO₂ avoided [t/year]", f"{full['co2_avoided_t']:,.0f}")
        c[3].metric("Primary-energy reduction", f"{100 * full['primary_energy_reduction']:.1f} %")
        left, right = st.columns(2)
        with left:
            _show(result.figures["electrification_curve"])
        with right:
            _show(result.figures["price_ratio_sweep"])
        if "scenarios" in result.tables:
            st.markdown("**Scenarios from the case file** (each overrides the named inputs on top of the sidebar values)")
            st.dataframe(result.tables["scenarios"], width="stretch")
        if s.get("retrofit") and "skipped" not in s["retrofit"]:
            st.markdown("**Retrofit of the existing network (step 5)**: options against the site as it is today")
            _show(result.figures["retrofit_options"])
            st.dataframe(result.tables["retrofit_options"], width="stretch")
        if "eta_lorenz_sensitivity" in result.tables:
            st.markdown("**Lorenz-efficiency sensitivity** (heat pumps re-sized)")
            st.dataframe(result.tables["eta_lorenz_sensitivity"], width="stretch")

with tab_dt:
    if not at or "skipped" in at:
        st.info(f"Supertargeting not run: {at.get('skipped', 'switched off or no film coefficients')}.")
    else:
        _show(result.figures["supertargeting"])
        st.dataframe(pd.DataFrame(at["RQ2"]), width="stretch")
        st.caption(f"Film coefficients: {at['film_coefficients_source']}")

with tab_src:
    st.markdown("**Provenance (case file)**")
    for k, v in s["provenance"].items():
        st.markdown(f"- **{k}**: {v}")
    if ec and "skipped" not in ec:
        st.markdown("**Economic inputs: sources**")
        for k, v in {**ec.get("default_sources", {}), **ec.get("case_sources", {})}.items():
            st.markdown(f"- **{k}**: {v}")
        st.caption("Values changed in the sidebar replace the case-file value but keep its source note above; "
                   "cite your own source for any value you change.")
    st.download_button("Download all results (zip)", _zip_outputs(result, case.name),
                       file_name=f"{case.name}_results.zip", mime="application/zip")
    st.download_button("Download summary (Markdown)", markdown(s), file_name=f"{case.name}_summary.md")
    st.download_button("Download summary (JSON)", json.dumps(s, indent=2, ensure_ascii=False, default=str),
                       file_name=f"{case.name}_summary.json")

result.close_figures()  # free memory: Streamlit reruns the script on every input change
