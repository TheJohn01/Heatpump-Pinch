"""Pinch analysis and heat pump design for any industrial site.

Usage
-----
    python analyse.py cases/brewery_padulles2026.json
    python analyse.py --all            # every case file in cases/ (except TEMPLATE)

For each case, writes to outputs/<case name>/:
    problem_table.csv          heat cascade
    composite_curves.png       shifted composite curves
    gcc.png                    Grand Composite Curve
    gcc_heat_pumps.png         GCC with the designed heat pumps
    heat_pump_design.csv       one row per heat pump
    summary.json, summary.md   targets, design, annual figures and warnings
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from pinch import energy_balance, load_streams, problem_table, with_extra_shift
from pinch.case import Case, load_case, to_MWh_per_year
from pinch.area_analysis import run_area_targeting
from pinch.economic_analysis import eta_lorenz_sensitivity, run_economics
from pinch.design import HeatPumpDesign, design_from_gcc, plausibility_warnings, source_warnings
from pinch.heat_pump import andersen2024_eta_lorenz
from pinch.plotting import plot_composite_curves, plot_gcc, plot_gcc_with_units

ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT / "cases"


def analyse(case: Case, output_root: Path = ROOT / "outputs") -> dict:
    """Run steps 1, 2 and 4 for one case and write all outputs. Returns the summary."""
    out = output_root / case.name
    out.mkdir(parents=True, exist_ok=True)

    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    unit = streams.energy_unit
    table = problem_table(streams)
    balance = energy_balance(streams)

    table.to_frame().to_csv(out / "problem_table.csv", index=False)
    plot_composite_curves(streams, table, out / "composite_curves.png", title=f"Shifted composite curves: {case.name}")
    plot_gcc(table, out / "gcc.png", title=f"Grand Composite Curve: {case.name}")

    design: HeatPumpDesign = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    r = design.integration
    rows = []
    for u in design.units:
        eta_A, eta_A_warn = andersen2024_eta_lorenz(u.T_source_in_C, u.T_sink_out_C,
                                                    u.T_source_out_C - u.T_source_in_C, u.T_sink_out_C - u.T_sink_in_C)
        rows.append({
            "unit": u.name,
            "T_sink_in_C": u.T_sink_in_C, "T_sink_out_C": u.T_sink_out_C,
            "T_source_C": u.T_source_out_C,
            f"Q_sink_{unit}": round(u.Q_sink, 4),
            "COP": round(u.COP, 3),
            f"W_{unit}": round(u.W, 4),
            f"Q_source_{unit}": round(u.Q_source, 4),
            f"source_from_process_{unit}": round(r.Q_source_process.get(u.name, 0.0), 4),
            f"source_external_{unit}": round(r.Q_source_external.get(u.name, 0.0), 4),
            "placement": r.placement[u.name],
            "eta_lorenz_Andersen2024_check": round(eta_A, 3),
            "Andersen2024_validity": "; ".join(eta_A_warn) or "within fitted range",
            "warnings": "; ".join(plausibility_warnings(u, case.screening)
                                  + source_warnings(design, case.ambient_T_C).get(u.name, [])),
        })
    pd.DataFrame(rows).to_csv(out / "heat_pump_design.csv", index=False)
    plot_gcc_with_units(table, list(design.units), out / "gcc_heat_pumps.png",
                        title=f"Heat pumps sized from the GCC: {case.name}")

    def annual(x):
        v = to_MWh_per_year(x, unit, case.basis)
        return None if v is None else round(v, 1)

    summary = {
        "case": case.name,
        "description": case.description,
        "reference": case.reference,
        "energy_unit": unit,
        "targets": {
            "Q_hot_total": round(balance["Q_hot_total"], 4),
            "Q_cold_total": round(balance["Q_cold_total"], 4),
            "Qh_min": round(table.Qh_min, 4),
            "Qc_min": round(table.Qc_min, 4),
            "heat_recovery": round(table.heat_recovery, 4),
            "pinch_T_star_C": list(table.pinch_T_star_C),
            "T_star_range_C": [float(table.T_star_C[0]), float(table.T_star_C[-1])],
        },
        "heat_pump_design": {
            "eta_lorenz": case.eta_lorenz,
            "units": [u.name for u in design.units],
            "levels_skipped_no_useful_duty": list(design.skipped),
            "Q_sink_total": round(design.Q_sink_total, 4),
            "W_total": round(design.W_total, 4),
            "COP_system": round(design.COP_system, 3),
            "Qh_residual": round(design.Qh_residual, 4),
            "fraction_of_Qh_min_electrified": round(design.fraction_electrified, 4),
            "cold_utility_replaced": round(r.Q_cold_utility_replaced, 4),
            "source_external_total": round(sum(r.Q_source_external.values()), 4),
        },
        "annual_MWh_per_year": None if case.basis is None else {
            "basis": case.basis,
            "Qh_min": annual(table.Qh_min),
            "Qc_min": annual(table.Qc_min),
            "heat_pump_electricity": annual(design.W_total),
            "residual_hot_utility": annual(design.Qh_residual),
        },
        "warnings": {u.name: w for u in design.units
                     if (w := plausibility_warnings(u, case.screening)
                         + source_warnings(design, case.ambient_T_C).get(u.name, []))},
        "provenance": case.provenance,
    }
    summary["economics"] = run_economics(case, design, balance["Q_cold_total"], unit, out)
    summary["eta_lorenz_sensitivity"] = eta_lorenz_sensitivity(case, streams, unit, out)
    summary["area_targeting"] = run_area_targeting(case, streams, out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def _markdown(s: dict) -> str:
    u, t, d = s["energy_unit"], s["targets"], s["heat_pump_design"]
    lines = [
        f"# {s['case']}", "", s["description"], "", f"Source: {s['reference']}", "",
        "## Energy targets", "",
        f"| Quantity | Value [{u}] |", "|---|---|",
        f"| Total hot / cold stream loads | {t['Q_hot_total']} / {t['Q_cold_total']} |",
        f"| Q̇h,min | {t['Qh_min']} |", f"| Q̇c,min | {t['Qc_min']} |",
        f"| Heat recovery | {t['heat_recovery']} |",
        f"| Pinch T* [°C] | {', '.join(str(p) for p in t['pinch_T_star_C']) or 'none (threshold)'} |", "",
        "## Heat pumps sized from the GCC", "",
        f"| Quantity | Value |", "|---|---|",
        f"| Units | {', '.join(d['units']) or 'none'} |",
        f"| Heat delivered [{u}] | {d['Q_sink_total']} |",
        f"| Electricity [{u}] | {d['W_total']} |",
        f"| System COP [-] | {d['COP_system']} |",
        f"| Residual hot utility [{u}] | {d['Qh_residual']} |",
        f"| Share of Q̇h,min electrified | {100 * d['fraction_of_Qh_min_electrified']:.1f} % |",
        f"| External (ambient) source [{u}] | {d['source_external_total']} |",
    ]
    if d["levels_skipped_no_useful_duty"]:
        lines += ["", f"Levels with no useful duty: {', '.join(d['levels_skipped_no_useful_duty'])}"]
    if s["annual_MWh_per_year"]:
        a = s["annual_MWh_per_year"]
        lines += ["", "## Annual figures [MWh/year]", "",
                  f"Basis: {a['basis']}", "",
                  f"Q̇h,min {a['Qh_min']}; Q̇c,min {a['Qc_min']}; heat pump electricity {a['heat_pump_electricity']}; "
                  f"residual hot utility {a['residual_hot_utility']}."]
    else:
        lines += ["", "No annual basis given: results stay in the stream-data unit."]
    ec = s.get("economics", {})
    if ec and "skipped" not in ec:
        r1, r3, full = ec["RQ1"], ec["RQ3"], ec["results"]["full design (heat recovery installed)"]
        lines += ["", "## Economics (step 6)", "",
                  f"Price ratio {ec['price_ratio']} (electricity {ec['parameters']['electricity_price_EUR_per_kWh']} EUR/kWh, "
                  f"gas {ec['parameters']['gas_price_EUR_per_kWh']} EUR/kWh); boiler efficiency "
                  f"{ec['parameters']['boiler_efficiency']}; {ec['parameters']['operating_hours_per_year']:.0f} h/year.", "",
                  "| Quantity | Value |", "|---|---|",
                  f"| Full design: CAPEX [EUR] | {full['capex_EUR']:,.0f} |",
                  f"| Full design: annual savings [EUR/year] | {full['savings_EUR']:,.0f} |",
                  f"| Full design: simple payback [years] | {full['payback_years']} |",
                  f"| Full design: NPV [EUR] | {full['npv_EUR']:,.0f} |",
                  f"| Full design: CO2 avoided [t/year] | {full['co2_avoided_t']:,.0f} |",
                  f"| Full design: primary-energy reduction | {100 * full['primary_energy_reduction']:.1f} % |",
                  f"| RQ1: largest share of Q̇h,min with payback ≤ {r1['threshold_years']:g} y | "
                  f"{100 * r1['max_fraction_with_payback_below_threshold']:.1f} % |",
                  f"| RQ1: share with maximum NPV | {100 * r1['fraction_with_max_NPV']:.1f} % |",
                  f"| RQ3: break-even ratio, NPV = 0 | {r3['break_even_ratio_NPV']} |",
                  f"| RQ3: break-even ratio, payback = threshold | {r3['break_even_ratio_payback']} |"]
        if ec.get("scenarios"):
            lines += ["", "### Scenarios (parameter overrides)", "",
                      "| Scenario | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | RQ1 | RQ3 (NPV = 0) |",
                      "|---|---|---|---|---|---|---|"]
            lines += [f"| {r['scenario']} | {r['price_ratio']} | {r['full_payback_years']} | {r['full_npv_EUR']:,.0f} | "
                      f"{r['full_co2_avoided_t']:,.0f} | {100 * r['RQ1_max_fraction_payback_ok']:.1f} % | "
                      f"{r['RQ3_break_even_ratio_NPV']} |" for r in ec["scenarios"]]
    elif ec:
        lines += ["", f"Economics skipped: {ec['skipped']}."]
    if s.get("eta_lorenz_sensitivity"):
        lines += ["", "### Lorenz-efficiency sensitivity (heat pumps re-sized)", "",
                  "| η_L | System COP | Full-design payback [y] | NPV [EUR] | RQ1 | RQ3 (NPV = 0) |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['eta_lorenz']} | {r['COP_system']} | {r['full_payback_years']} | {r['full_npv_EUR']:,.0f} | "
                  f"{100 * r['RQ1_max_fraction_payback_ok']:.1f} % | {r['RQ3_break_even_ratio_NPV']} |"
                  for r in s["eta_lorenz_sensitivity"]]
    at = s.get("area_targeting", {})
    if at and "skipped" not in at:
        lines += ["", "## ΔTmin supertargeting (step 3, RQ2)", "",
                  f"Hot utility {at['hot_utility_cost_EUR_per_kW_year']} EUR/kW-year; cold utility "
                  f"{at['cold_utility_cost_EUR_per_kW_year']} EUR/kW-year; CRF {at['crf_per_year']}/year. "
                  f"Film coefficients: {at['film_coefficients_source']}", "",
                  "| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |", "|---|---|---|---|---|"]
        lines += [f"| {r['cost_law']} | {r['dTmin_opt_K']:g}{' (grid edge)' if r['at_grid_edge'] else ''} | "
                  f"{r['area_m2']:,.0f} | {r['Qh_min_kW']:,.0f} | {r['TAC_min_EUR']:,.0f} |" for r in at["RQ2"]]
    if s["warnings"]:
        lines += ["", "## Plausibility warnings", ""] + [f"- **{k}**: {'; '.join(v)}" for k, v in s["warnings"].items()]
    if s["provenance"]:
        lines += ["", "## Provenance", ""] + [f"- **{k}**: {v}" for k, v in s["provenance"].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_files", nargs="*", type=Path, help="case JSON files")
    parser.add_argument("--all", action="store_true", help="run every case in cases/")
    args = parser.parse_args()
    files = sorted(p for p in CASES_DIR.glob("*.json") if p.stem != "TEMPLATE") if args.all else args.case_files
    if not files:
        parser.error("give one or more case files, or --all")
    for f in files:
        s = analyse(load_case(f))
        d = s["heat_pump_design"]
        print(f"{s['case']}: Qh_min {s['targets']['Qh_min']} {s['energy_unit']}, "
              f"HP electricity {d['W_total']}, electrified {100 * d['fraction_of_Qh_min_electrified']:.1f} %, "
              f"warnings: {sum(len(v) for v in s['warnings'].values())}")


if __name__ == "__main__":
    main()
