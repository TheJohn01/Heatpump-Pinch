"""One table that reconciles the heat pump numbers reported in different places (step 4b, 6).

Usage:
    python -m scripts.checks.design_consistency_check cases/brewery.json

The repository reports several COPs and costs for the same heat pump unit. They are not in conflict:
each belongs to a differently defined model. This check puts them side by side, says which one is the
basis of the economics and why, and verifies the order a sound model must respect.

1. COP per unit and method
   * basis: Lorenz model with the case's η_L (cases/<case>.json, ``heat_pumps.eta_lorenz``; author
     decision documented in ``provenance.eta_lorenz``);
   * Lorenz model with the paper's η_L = 0.55 (Padullés et al. 2026, Sec. 4.3.1; sensitivity row);
   * Andersen et al. (2024) polynomial: reported only as an extrapolation when the unit lies outside the
     fitted range (their Sec. 2.5), never as a check;
   * cycle model with losses (pinch.cycle, CoolProp; selected fluid and layout, 5 % heat loss, motor 0.95,
     Andersen et al. 2024 Table 3): outputs/<case>/cycle_screening.json;
   * idealised single-stage cycle (no heat loss, motor 1, no SLHX), from pinch.cycle and from TESPy:
     outputs/<case>/heat_pump_partload.csv (a model-to-model check, not a design value);
   * reversible Lorenz COP (η_L = 1): the second-law bound every value must stay below.
2. Heat pump CAPEX: the case's cost function (Padullés Table 3, the basis) against the component cost of
   Kosmadakis et al. (2020) as implemented in heatpumps (outputs/<case>/heat_pump_cost_check.csv).
3. The case's design against the paper's configuration 2 (two heat pumps; data/brewery_configurations.json)
   and our reproduction of it (outputs/step4_partA_totals.csv).

Verdicts (pinned in tests/test_reproductions.py):
    V1 every COP is below the reversible Lorenz COP of its unit;
    V2 pinch.cycle and TESPy agree on the idealised cycle within 0.5 %;
    V3 the basis COP is not optimistic: it does not exceed the highest defensible method (cycle model
       with losses, paper's η_L). The detail reports how far below the lowest of them it lies; for the
       brewery HTHP the case's η_L = 0.50 is 7.6 % below the cascade-cycle model (conservative). Whether to
       use a per-unit η_L from the cycle model instead is an author decision (docs/ASSUMPTIONS.md);
    V4 the two CAPEX methods agree within the DEA band used for the CAPEX sensitivity (±25 %);
    V5 the reproduction of configuration 2 is within 5 % of the published work.

Writes outputs/<case>/design_consistency.csv and .md.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from pinch.case import load_case
from pinch.heat_pump import andersen2024_eta_lorenz, lorenz_cop

ROOT = Path(__file__).resolve().parents[2]   # repository root
PAPER_ETA = 0.55          # Padullés et al. (2026), Sec. 4.3.1
CAPEX_BAND = 0.25         # DEA sheet 2.a range used for the "Heat pump CAPEX ±25 %" rows
CYCLE_AGREEMENT = 0.005   # V2
REPRO_TOLERANCE = 0.05    # V5


def _row(section: str, unit: str, method: str, value: float, status: str, source: str, quantity: str = "COP",
         eta: float = math.nan) -> dict:
    return {"section": section, "unit": unit, "quantity": quantity, "method": method,
            "eta_lorenz": round(eta, 4) if eta == eta else math.nan, "value": round(value, 4),
            "status": status, "source": source}


def checks(case_file: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(table, verdicts) for one case; reads committed outputs only."""
    case = load_case(case_file)
    out = ROOT / "outputs" / case.name
    design = pd.read_csv(out / "heat_pump_design.csv")
    screening = json.loads((out / "cycle_screening.json").read_text(encoding="utf-8")).get("selected", {})
    partload = pd.read_csv(out / "heat_pump_partload.csv") if (out / "heat_pump_partload.csv").exists() else None
    cost = pd.read_csv(out / "heat_pump_cost_check.csv") if (out / "heat_pump_cost_check.csv").exists() else None

    rows: list[dict] = []
    verdicts: list[dict] = []
    for _, u in design.iterrows():
        name = u["unit"]
        T = (u["T_sink_in_C"], u["T_sink_out_C"], u["T_source_C"], u["T_source_C"])
        cop_rev = lorenz_cop(*T, 1.0)
        eta_basis = u["COP"] / cop_rev
        rows.append(_row("1 COP", name, "Reversible Lorenz COP (second-law bound)", cop_rev, "bound",
                         "pinch.heat_pump.lorenz_cop, η_L = 1", eta=1.0))
        rows.append(_row("1 COP", name, "Lorenz model, case η_L (basis of the economics)", u["COP"], "basis",
                         "cases/<case>.json heat_pumps.eta_lorenz; provenance.eta_lorenz", eta=eta_basis))
        rows.append(_row("1 COP", name, "Lorenz model, paper η_L 0.55", PAPER_ETA * cop_rev, "sensitivity row",
                         "Padullés et al. (2026), Sec. 4.3.1", eta=PAPER_ETA))
        eta_A, warn = andersen2024_eta_lorenz(T[2], T[1], 0.0, T[1] - T[0])
        rows.append(_row("1 COP", name, "Andersen et al. (2024) polynomial", eta_A * cop_rev,
                         "extrapolated, not a check" if warn else "check",
                         "Applied Energy 376, 124312, Sec. 3.2" + (f" ({'; '.join(warn)})" if warn else ""),
                         eta=eta_A))
        values = [u["COP"], PAPER_ETA * cop_rev, eta_A * cop_rev]
        sel = screening.get(name)
        if sel:
            rows.append(_row("1 COP", name, f"Cycle model with losses ({sel['fluid']}, {sel['layout']})", sel["COP"],
                             "check; 'Cycle-based COP' sensitivity row", "outputs/<case>/cycle_screening.json",
                             eta=sel["eta_lorenz_cycle"]))
            values.append(sel["COP"])
        ideal = None
        if partload is not None:
            p = partload[(partload["unit"] == name) & (partload["load_fraction"] == 1.0)]
            if len(p) and p["COP_pinch_cycle"].notna().all():
                ideal = (float(p["COP_pinch_cycle"].iloc[0]), float(p["COP_tespy"].iloc[0]))
                rows.append(_row("1 COP", name, "Idealised single-stage cycle, pinch.cycle", ideal[0],
                                 "model check (no losses, no SLHX)", "outputs/<case>/heat_pump_partload.csv",
                                 eta=ideal[0] / cop_rev))
                rows.append(_row("1 COP", name, "Idealised single-stage cycle, TESPy", ideal[1],
                                 "model check (no losses, no SLHX)", "outputs/<case>/heat_pump_partload.csv",
                                 eta=ideal[1] / cop_rev))
                values += list(ideal)
        verdicts.append({"verdict": "V1", "unit": name, "passed": bool(max(values) < cop_rev),
                         "detail": f"max COP {max(values):.3f} < reversible {cop_rev:.3f}"})
        if ideal:
            dev = abs(ideal[1] / ideal[0] - 1)
            verdicts.append({"verdict": "V2", "unit": name, "passed": bool(dev <= CYCLE_AGREEMENT),
                             "detail": f"TESPy/pinch.cycle - 1 = {100 * dev:.3f} %"})
        lo = min(sel["COP"] if sel else u["COP"], PAPER_ETA * cop_rev)
        hi = max(sel["COP"] if sel else u["COP"], PAPER_ETA * cop_rev)
        below = max(0.0, 1 - u["COP"] / lo)
        verdicts.append({"verdict": "V3", "unit": name, "passed": bool(u["COP"] <= hi + 1e-9),
                         "detail": f"basis {u['COP']:.3f} vs defensible range [{lo:.3f}, {hi:.3f}] (cycle with losses, "
                                   f"paper η_L): " + (f"conservative, {100 * below:.1f} % below" if below > 0
                                                      else "within the range")})

    if cost is not None:
        for _, c in cost.iterrows():
            rows.append(_row("2 CAPEX", c["unit"], "Case cost function (Padullés Table 3)",
                             c["case_cost_function_EUR"], "basis", "cases/<case>.json economics", "CAPEX_EUR"))
            rows.append(_row("2 CAPEX", c["unit"], "Kosmadakis et al. (2020) component cost (heatpumps)",
                             c["total_capital_EUR"], "check; 'Heat pump CAPEX -8 %' sensitivity row",
                             str(c["method"]), "CAPEX_EUR"))
            ratio = c["total_capital_EUR"] / c["case_cost_function_EUR"]
            verdicts.append({"verdict": "V4", "unit": c["unit"], "passed": bool(abs(ratio - 1) <= CAPEX_BAND),
                             "detail": f"Kosmadakis / case = {ratio:.3f} (band ±{CAPEX_BAND:.0%})"})

    cfg_file = ROOT / "data" / f"{case.name}_configurations.json"
    totals = ROOT / "outputs" / "step4_partA_totals.csv"
    if cfg_file.exists() and totals.exists():
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))["config_2_two_hp"]["units"]
        for unit_paper, (_, ours) in zip(cfg, design.iterrows()):
            rows.append(_row("3 vs paper config. 2", ours["unit"], f"Published: {unit_paper['name']}",
                             unit_paper["Q_sink"], "published", "Padullés et al. (2026), Fig. 14", "Q_sink"))
            rows.append(_row("3 vs paper config. 2", ours["unit"], "Case design (GCC sizing)",
                             ours[[c for c in design.columns if c.startswith("Q_sink_")][0]], "reproduced",
                             "outputs/<case>/heat_pump_design.csv", "Q_sink"))
            rows.append(_row("3 vs paper config. 2", ours["unit"], f"Published: {unit_paper['name']}",
                             unit_paper["W_published"], "published", "Padullés et al. (2026), Fig. 14", "W"))
            rows.append(_row("3 vs paper config. 2", ours["unit"], "Case design (GCC sizing)",
                             ours[[c for c in design.columns if c.startswith("W_")][0]], "reproduced",
                             "outputs/<case>/heat_pump_design.csv", "W"))
        t = pd.read_csv(totals)
        r = t[t["configuration"].str.startswith("2")].iloc[0]
        verdicts.append({"verdict": "V5", "unit": "configuration 2", "passed": bool(abs(r["deviation_%"]) <= 100 * REPRO_TOLERANCE),
                         "detail": f"W reproduced {r['W_ours']:.3f} vs published {r['W_published']:.3f} "
                                   f"({r['deviation_%']:+.2f} %)"})
    return pd.DataFrame(rows), pd.DataFrame(verdicts)


def markdown(table: pd.DataFrame, verdicts: pd.DataFrame, eta_case: float) -> str:
    lines = ["# Heat pump numbers: which value is the basis, and how the others relate", "",
             f"Basis of the economics: **Lorenz model with η_L = {eta_case:g}** (case file, provenance.eta_lorenz) and "
             "the **case's heat pump cost function** (Padullés et al. 2026, Table 3). Every other value below is a "
             "check, a sensitivity row or a bound. Generated by `scripts/checks/design_consistency_check.py`.", ""]
    for section, g in table.groupby("section", sort=True):
        lines += [f"## {section}", "", "| Unit | Quantity | Method | η_L | Value | Status |", "|---|---|---|---|---|---|"]
        for _, r in g.iterrows():
            eta = "" if r["eta_lorenz"] != r["eta_lorenz"] else f"{r['eta_lorenz']:.3f}"
            val = f"{r['value']:,.0f}" if r["quantity"] == "CAPEX_EUR" else f"{r['value']:.3f}"
            lines.append(f"| {r['unit']} | {r['quantity']} | {r['method']} | {eta} | {val} | {r['status']} |")
        lines.append("")
    lines += ["## Verdicts", "", "| Verdict | Unit | Passed | Detail |", "|---|---|---|---|"]
    lines += [f"| {v['verdict']} | {v['unit']} | {'yes' if v['passed'] else 'NO'} | {v['detail']} |"
              for _, v in verdicts.iterrows()]
    lines += ["", "Configuration 2 is sized by the paper from its own figures (8.3 + 2.4 kWh/hl, including heat beyond "
              "Q̇h,min); the case design sizes the units from the GCC to Q̇h,min (10.04 kWh/hl in total), so its "
              "duties and work differ by design. The like-for-like reproduction is V5.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = load_case(args.case)
    table, verdicts = checks(args.case)
    out = ROOT / "outputs" / case.name
    eta_case = float(json.loads(args.case.read_text(encoding="utf-8"))["heat_pumps"]["eta_lorenz"])
    pd.concat([table, verdicts.rename(columns={"detail": "source"}).assign(section="verdict")], ignore_index=True) \
        .to_csv(out / "design_consistency.csv", index=False)
    (out / "design_consistency.md").write_text(markdown(table, verdicts, eta_case), encoding="utf-8")
    failed = verdicts[~verdicts["passed"]]
    print(f"{case.name}: {len(verdicts) - len(failed)} of {len(verdicts)} verdicts pass")


if __name__ == "__main__":
    main()
