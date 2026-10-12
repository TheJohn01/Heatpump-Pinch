"""Workflow step 4: heat pump placement, COP and electricity for the brewery.

Part A  Reproduce the paper's electricity use from its published heat flows,
        using the Lorenz COP model (Padullés et al., 2026, Eq. 1).
Part B  Check each configuration against the minimum-energy cascade of the
        process: placement relative to the pinch, useful sink heat, source
        heat taken from the process vs. from ambient.
Part C  Our own design sized from the GCC (minimum energy, two heat pumps).

Usage:  python run_heat_pumps.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pinch import load_streams, problem_table
from pinch.heat_pump import HeatPump, integrate, max_useful_sink_duty
from pinch.plotting import plot_gcc_with_units
from pinch.validation import ROOT


@dataclass(frozen=True)
class Config:
    """Run parameters. Process data and configurations are read from files."""

    stream_file: Path = ROOT / "data" / "brewery_streams.csv"
    configuration_file: Path = ROOT / "data" / "brewery_configurations.json"
    output_dir: Path = ROOT / "outputs"
    steam_T_sweep_C: tuple[float, ...] = tuple(np.arange(100.0, 181.0, 5.0))


def build_unit(spec: dict, eta_lorenz: float) -> HeatPump:
    """Create a HeatPump from a configuration entry."""
    common = dict(name=spec["name"], Q_sink=spec["Q_sink"],
                  T_sink_in_C=spec["T_sink_in_C"], T_sink_out_C=spec["T_sink_out_C"],
                  T_source_in_C=spec.get("T_source_in_C"), T_source_out_C=spec.get("T_source_out_C"))
    if spec["model"] == "lorenz":
        return HeatPump(**common, eta_lorenz=eta_lorenz)
    return HeatPump(**common, cop_fixed=spec["COP"])


def unit_row(config_name: str, unit: HeatPump, spec: dict) -> dict:
    W_pub = spec.get("W_published", np.nan)
    return {
        "configuration": config_name,
        "unit": unit.name,
        "Q_sink_kWh_hl": unit.Q_sink,
        "COP_ours": round(unit.COP, 3),
        "COP_published": spec.get("COP_published", spec.get("COP", np.nan)),
        "COP_reversible": round(unit.cop_reversible, 2),
        "W_ours_kWh_hl": round(unit.W, 3),
        "W_published_kWh_hl": W_pub,
        "W_deviation_kWh_hl": round(unit.W - W_pub, 3) if not np.isnan(W_pub) else np.nan,
    }


def main(config: Config = Config()) -> None:
    out = config.output_dir
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(config.configuration_file.read_text(encoding="utf-8"))
    eta = cfg["eta_lorenz"]["value"]
    T_cold_C = cfg["cold_utility_T_C"]["value"]
    streams = load_streams(config.stream_file)
    base = problem_table(streams)

    # ------------------------------------------------------------- Part A
    rows, totals = [], []
    c2 = cfg["config_2_two_hp"]
    units_2 = [build_unit(s, eta) for s in c2["units"]]
    rows += [unit_row("2: two HP", u, s) for u, s in zip(units_2, c2["units"])]
    totals.append({"configuration": "2: two HP", "W_ours": sum(u.W for u in units_2),
                   "W_published": c2["W_total_published"]["value"]})

    c3 = cfg["config_3_fully_integrated"]
    units_3_common = [build_unit(s, eta) for s in c3["units_common"]]
    units_3 = {}
    for key, spec in c3["booster_options"].items():
        booster = build_unit(spec, eta)
        units_3[key] = units_3_common + [booster]
        name = f"3: fully integrated ({key})"
        specs = c3["units_common"] + [spec]
        rows += [unit_row(name, u, s) for u, s in zip(units_3[key], specs)]
        totals.append({"configuration": name, "W_ours": sum(u.W for u in units_3[key]),
                       "W_published": c3["W_total_published"][key]})

    part_a = pd.DataFrame(rows)
    part_a_totals = pd.DataFrame(totals)
    part_a_totals["deviation"] = part_a_totals["W_ours"] - part_a_totals["W_published"]
    part_a_totals["deviation_%"] = 100 * part_a_totals["deviation"] / part_a_totals["W_published"]
    part_a.to_csv(out / "step4_partA_units.csv", index=False)
    part_a_totals.round(3).to_csv(out / "step4_partA_totals.csv", index=False)

    # Configuration 1: sweep of steam temperature (Fig. 11)
    c1 = cfg["config_1_cchs"]
    sweep = []
    for T_steam in config.steam_T_sweep_C:
        row = {"T_steam_C": T_steam}
        for label, Q in (("with_HR", c1["Q_sink_with_HR"]["value"]), ("no_HR", c1["Q_sink_no_HR"]["value"])):
            unit = HeatPump("CCHS", Q, T_steam, T_steam, T_cold_C, T_cold_C, eta_lorenz=eta)
            row[f"COP_{label}"] = unit.COP
            row[f"W_{label}_kWh_hl"] = unit.W
        sweep.append(row)
    sweep = pd.DataFrame(sweep)
    sweep.round(3).to_csv(out / "step4_config1_sweep.csv", index=False)

    fig_rows = []
    for label, key in (("with_HR", "W_figure_with_HR"), ("no_HR", "W_figure_no_HR")):
        for T, W_fig in c1[key]["points"].items():
            W_ours = float(np.interp(float(T), sweep["T_steam_C"], sweep[f"W_{label}_kWh_hl"]))
            fig_rows.append({"case": label, "T_steam_C": float(T), "W_figure": W_fig,
                             "W_ours": round(W_ours, 2), "deviation_%": round(100 * (W_ours - W_fig) / W_fig, 1)})
    config1_check = pd.DataFrame(fig_rows)
    config1_check.to_csv(out / "step4_config1_vs_fig11.csv", index=False)

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for label, colour, name in (("with_HR", "#2E7D32", "With heat recovery"), ("no_HR", "#2471A3", "No heat recovery")):
        ax.plot(sweep["T_steam_C"], sweep[f"W_{label}_kWh_hl"], color=colour, lw=2, label=f"{name} (this work)")
        pts = c1[f"W_figure_{label}"]["points"]
        ax.errorbar([float(t) for t in pts], list(pts.values()), yerr=c1[f"W_figure_{label}"]["uncertainty"],
                    fmt="o", color=colour, mfc="white", capsize=3, label=f"{name} (read from Fig. 11)")
    ax.axvline(base.T_star_C[0], color="grey", ls=":", lw=1)
    ax.annotate("GCC maximum T* = 103 °C", xy=(base.T_star_C[0], 1), xytext=(4, 0),
                textcoords="offset points", fontsize=8, color="grey")
    ax.set_xlabel("Utility steam temperature [°C]")
    ax.set_ylabel("Electricity consumption [kWh/hl]")
    ax.set_ylim(0, 25)
    ax.set_title("Configuration 1 (CCHS): this work vs. Padullés et al. (2026)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "step4_config1_vs_fig11.png", dpi=200)
    plt.close(fig)

    # ------------------------------------------------------------- Part B
    checks = []
    cases = {
        "1: CCHS at 103 °C (with HR)": [HeatPump("CCHS", c1["Q_sink_with_HR"]["value"], 103, 103,
                                                 T_cold_C, T_cold_C, eta_lorenz=eta)],
        "2: two HP": units_2,
        "3: fully integrated (EB)": units_3["EB"],
        "3: fully integrated (HTHP)": units_3["HTHP"],
    }
    for name, units in cases.items():
        r = integrate(streams, units)
        checks.append({
            "configuration": name,
            "Q_sink_total": round(r.Q_sink_total, 3),
            "Qh_min_process": round(r.Qh_before, 3),
            "Q_sink_useful": round(r.Q_sink_useful, 3),
            "Q_sink_excess": round(r.Q_sink_excess, 3),
            "Qh_after": round(r.Qh_after, 3),
            "Qc_after": round(r.Qc_after, 3),
            "source_from_process": round(sum(r.Q_source_process.values()), 3),
            "source_external": round(sum(r.Q_source_external.values()), 3),
            "W_total": round(r.W_total, 3),
            "placement": "; ".join(f"{k}: {v}" for k, v in r.placement.items()),
        })
    part_b = pd.DataFrame(checks)
    part_b.to_csv(out / "step4_partB_integration.csv", index=False)

    # ------------------------------------------------------------- Part C
    # Minimum-energy design: CO2 HP sized from the GCC (same temperatures as
    # the paper), HTHP at the GCC maximum T* for the remaining hot utility.
    co2_template = HeatPump("CO2 HP", 1.0, 18, 82, T_cold_C, T_cold_C, eta_lorenz=eta)
    Q_co2 = max_useful_sink_duty(streams, co2_template)
    co2 = co2_template.with_sink_duty(Q_co2)
    Q_hthp = base.Qh_min - Q_co2
    hthp = HeatPump("HTHP", Q_hthp, base.T_star_C[0], base.T_star_C[0], T_cold_C, T_cold_C, eta_lorenz=eta)
    design = [co2, hthp]
    r = integrate(streams, design)
    part_c = pd.DataFrame([{
        "unit": u.name, "Q_sink": round(u.Q_sink, 3), "COP": round(u.COP, 3), "W": round(u.W, 3),
        "Q_source": round(u.Q_source, 3), "source_from_process": round(r.Q_source_process[u.name], 3),
        "source_external": round(r.Q_source_external[u.name], 3), "placement": r.placement[u.name],
    } for u in design])
    part_c.to_csv(out / "step4_partC_mer_design.csv", index=False)

    plot_gcc_with_units(base, units_2, out / "step4_gcc_config2.png",
                        title="Configuration 2 (paper's duties) on the minimum-energy GCC")
    plot_gcc_with_units(base, design, out / "step4_gcc_mer_design.png",
                        title="Minimum-energy two-heat-pump design sized from the GCC")

    pd.set_option("display.width", 200)
    print("\nPart A: units\n" + part_a.to_string(index=False))
    print("\nPart A: totals\n" + part_a_totals.round(3).to_string(index=False))
    print("\nConfiguration 1 vs Fig. 11\n" + config1_check.to_string(index=False))
    print("\nPart B: integration into the minimum-energy cascade\n" + part_b.to_string(index=False))
    print(f"\nPart C: minimum-energy design (Qh_min = {base.Qh_min:.3f} kWh/hl)\n" + part_c.to_string(index=False))
    print(f"   W_total = {sum(u.W for u in design):.3f} kWh/hl;  Qh_after = {r.Qh_after:.3f};  Qc_after = {r.Qc_after:.3f}")


if __name__ == "__main__":
    main()
