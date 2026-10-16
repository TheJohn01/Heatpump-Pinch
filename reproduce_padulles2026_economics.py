"""Reproduction of Padullés et al. (2026), Sec. 5 (brewery economics; workflow step 6).

Energy flows per hectolitre are those reproduced in step 4 (reproduce_padulles2026.py);
cost functions, 8000 h/year, gas 0.06 EUR/kWh, 5 % / 10 years, and the 4-year
payback threshold are published (Sec. 5.1-5.2). The heat-recovery tank is sized
linearly with production from the one published point (375 m3 for 720,000 hl/year,
Sec. 5.1). Boiler efficiency: 1.0 (bound; not stated in the paper).

Checks the paper's qualitative statements S1-S4 (Sec. 5.2) and draws our version
of Figs. 18-19 (PBP- and NPV10-optimal option by brewery size and price ratio).

Usage:  python reproduce_padulles2026_economics.py
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pinch.economics import NO_OM, Option, capacity_kW, evaluate, load_economics
from pinch.heat_pump import HeatPump
from pinch.validation import ROOT

OUT = ROOT / "outputs"
PAPER_PBP_THRESHOLD = 4.0   # published, Sec. 5.2
TANK_M3_PER_HL = 375 / 720_000  # published point, Sec. 5.1 (text: DK 1 = 720,000 hl/year)
ETA = 0.55

# Heat delivered per unit [kWh/hl] and COP model: published flows (Figs. 14, 17; Sec. 4.3)
UNITS = {
    "CCHS (103 °C)": HeatPump("CCHS", 11.3, 103, 103, -1, -1, eta_lorenz=ETA),
    "CO2 HP (8.3)": HeatPump("CO2 HP", 8.3, 18, 82, -1, -1, eta_lorenz=ETA),
    "HTHP (2.4)": HeatPump("HTHP", 2.4, 103, 103, -1, -1, eta_lorenz=ETA),
    "CO2 HP (9.7)": HeatPump("CO2 HP", 9.7, 18, 82, -1, -1, eta_lorenz=ETA),
    "MVR": HeatPump("MVR", 2.6, 110, 110, 100, 100, cop_fixed=15),
    "EB booster": HeatPump("EB", 1.4, 87, 98, cop_fixed=1.0),
    "HTHP booster": HeatPump("HTHP booster", 1.4, 87, 98, -1, -1, eta_lorenz=ETA),
}
CONFIGS = {  # name -> [(unit key, cost-function kind)]
    "1: central HTHP": [("CCHS (103 °C)", "heat_pump")],
    "2: two HPs": [("CO2 HP (8.3)", "heat_pump"), ("HTHP (2.4)", "heat_pump")],
    "3: integrated (EB)": [("CO2 HP (9.7)", "heat_pump"), ("MVR", "mvr"), ("EB booster", "electric_boiler")],
    "3: integrated (HTHP)": [("CO2 HP (9.7)", "heat_pump"), ("MVR", "mvr"), ("HTHP booster", "heat_pump")],
}
HEAT_NO_HR = 21.4     # kWh/hl, Table 2 total heat demand
HEAT_WITH_HR = 11.3   # kWh/hl after Pfaduko + wort-cooling heat recovery (Sec. 4.3.2, 7)


def options_for(production_hl: float, hr_installed: bool, params) -> tuple[Option, list[Option]]:
    """Baseline and full-electrification options for a brewery size [hl/year]."""
    to_MWh = production_hl / 1000  # kWh/hl x hl/year -> MWh/year
    tank = () if hr_installed else (("hr_tank", TANK_M3_PER_HL * production_hl),)
    baseline = Option("baseline", (HEAT_WITH_HR if hr_installed else HEAT_NO_HR) * to_MWh, 0.0)
    options = []
    for name, parts in CONFIGS.items():
        W = sum(UNITS[k].W for k, _ in parts) * to_MWh
        equipment = tank + tuple((kind, capacity_kW(UNITS[k].Q_sink * to_MWh, params)) for k, kind in parts)
        options.append(Option(name, 0.0, W, equipment))
    return baseline, options


def best(production_hl, ratio, hr_installed, params, criterion):
    p = params.with_ratio(ratio)
    baseline, options = options_for(production_hl, hr_installed, p)
    evals = [evaluate(o, baseline, p) for o in options]
    if criterion == "pbp":
        return min(evals, key=lambda e: e.payback_years)
    return max(evals, key=lambda e: e.npv_EUR)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    params = load_economics({"gas_price_EUR_per_kWh": 0.06, "boiler_efficiency": 1.0, "gas_EF_kg_per_kWh": 0.219,
                             "operating_hours_per_year": 8000, "discount_rate": 0.05, "horizon_years": 10,
                             **NO_OM})   # the paper includes no O&M

    rows = []
    for size in (0.25e6, 0.5e6, 0.75e6, 1.0e6, 1.5e6):
        for hr in (False, True):
            for ratio in (1.0, 1.5, 2.0, 2.5, 3.0):
                p = params.with_ratio(ratio)
                baseline, options = options_for(size, hr, p)
                for o in options:
                    e = evaluate(o, baseline, p)
                    rows.append({"production_hl": size, "hr_installed": hr, "ratio": ratio, **e.as_dict()})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "step6_padulles_economics.csv", index=False)

    checks = []

    def check(name, statement, passed, detail):
        checks.append({"check": name, "statement": statement, "reproduced": bool(passed), "detail": detail})
        print(f"[{name}] {'REPRODUCED' if passed else 'NOT reproduced'}: {statement}\n      {detail}")

    b1 = best(0.25e6, 1.0, False, params, "pbp"); b2 = best(0.25e6, 2.0, False, params, "pbp")
    bh = best(0.25e6, 1.0, True, params, "pbp")
    check("S1", "Small breweries (< 0.5 Mhl/y) need a ratio close to 1 for PBP <= 4 y; with HR installed, electrification alone fails",
          b1.payback_years <= PAPER_PBP_THRESHOLD < b2.payback_years and bh.payback_years > PAPER_PBP_THRESHOLD,
          f"0.25 Mhl/y no HR: best PBP {b1.payback_years:.2f} y at r=1 ({b1.option}), {b2.payback_years:.2f} y at r=2; "
          f"HR installed, r=1: {bh.payback_years:.2f} y")

    m = best(0.75e6, 2.0, False, params, "pbp"); mh = best(0.75e6, 2.0, True, params, "pbp")
    check("S2", "Medium breweries (0.5-1 Mhl/y) reach PBP < 4 y at ratio ~2 thanks to HR; with HR installed they fail",
          m.payback_years < PAPER_PBP_THRESHOLD < mh.payback_years,
          f"0.75 Mhl/y r=2: no HR {m.payback_years:.2f} y ({m.option}); HR installed {mh.payback_years:.2f} y ({mh.option})")

    l2 = best(1.5e6, 2.0, False, params, "pbp")
    check("S3", "Large breweries (> 1 Mhl/y): lower PBPs at typical ratios; two-HP configurations can be preferred",
          l2.payback_years < m.payback_years and l2.option.startswith("2"),
          f"1.5 Mhl/y r=2: best PBP {l2.payback_years:.2f} y ({l2.option})")

    ns = best(0.25e6, 2.0, False, params, "npv"); nl = best(1.5e6, 2.0, False, params, "npv")
    check("S4", "NPV10 (5 %): small breweries positive with HR at common ratios; central HTHP for small, two HPs for larger",
          ns.npv_EUR > 0 and ns.option.startswith("1") and nl.option.startswith("2"),
          f"0.25 Mhl/y r=2: {ns.option}, NPV {ns.npv_EUR / 1e6:.2f} M EUR; 1.5 Mhl/y r=2: {nl.option}")
    pd.DataFrame(checks).to_csv(OUT / "step6_padulles_checks.csv", index=False)

    # Our version of Figs. 18-19: optimal option map
    sizes = np.linspace(0.2e6, 1.6e6, 57)
    ratios = np.linspace(1.0, 3.5, 51)
    names = list(CONFIGS)
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True, sharey=True)
    for col, criterion in enumerate(("pbp", "npv")):
        for row, hr in enumerate((False, True)):
            ax = axes[row, col]
            grid = np.zeros((len(ratios), len(sizes)))
            metric = np.zeros_like(grid)
            for i, r in enumerate(ratios):
                for j, s in enumerate(sizes):
                    e = best(s, r, hr, params, criterion)
                    ok = e.payback_years <= PAPER_PBP_THRESHOLD if criterion == "pbp" else e.npv_EUR > 0
                    grid[i, j] = names.index(e.option) if ok else -1
                    metric[i, j] = e.payback_years if criterion == "pbp" else e.npv_EUR / 1e6
            cmap = plt.matplotlib.colors.ListedColormap(["#E6E6E6", "#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD"])
            ax.pcolormesh(sizes / 1e6, ratios, grid, cmap=cmap, vmin=-1.5, vmax=3.5, shading="auto")
            levels = (2, 3, 4, 6, 8) if criterion == "pbp" else (-2, 0, 2, 5, 10)
            cs = ax.contour(sizes / 1e6, ratios, np.clip(metric, -50, 50), levels=levels, colors="k", linewidths=0.7)
            ax.clabel(cs, fmt="%g", fontsize=7)
            ax.set_title(f"{'PBP' if criterion == 'pbp' else 'NPV10'}-optimal, "
                         f"{'heat recovery installed' if hr else 'no heat recovery (tank included)'}", fontsize=9)
            if row == 1:
                ax.set_xlabel("Brewery size [million hl/year]")
            if col == 0:
                ax.set_ylabel("Electricity-to-gas price ratio [-]")
    handles = [plt.matplotlib.patches.Patch(color=c, label=l) for c, l in
               zip(["#E6E6E6", "#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD"],
                   ["not viable (PBP > 4 y / NPV10 < 0)"] + names)]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=8)
    fig.suptitle("Optimal electrification option (this work; compare Padullés et al. 2026, Figs. 18-19). "
                 "Isolines: PBP [years] / NPV10 [M EUR]", fontsize=10)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    fig.savefig(OUT / "step6_padulles_option_maps.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
