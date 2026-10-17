"""Verification of the Walmsley et al. (2024) dairy cases (Energies 17, 2838).

Checks
------
W1  Milk evaporator (Table 2): targets vs Fig. 8 (Q_D 3.54 MW, Q_S 0.46 MW).
W2  Milk evaporator: pinch range 7.5-10.5 °C from Table 2 vs 5.5-10.5 °C in
    the text; explained by the chiller-water dT_cont (0.5 K in Table 2, 2.5 K
    reproduces the text).
W3  Simple-design COP: one heat pump from ambient (15 °C dead state) to 105 °C
    with 50 % exergetic (Carnot) efficiency; text gives COP 2.1.
W4  Simple-design work: Fig. 11 marker (digitised 2.00 MW) vs Qh_min / COP.
    The marker comes from Lincoln et al. (ref. [15]), a practical design.
W5  Spray dryer (Table 1): published targets (4.98 / 3.99 MW) vs first law.
W6  Spray dryer: inferred stream variant that reproduces the published targets
    (Exhaust 2 ending at 23 °C, fluidised bed starting at 25 °C). INFERRED, not
    published: read from Fig. 5A/B (hot composite ends near 23 °C, cold
    composite starts near 25 °C, GCC bottom T* about 15 °C).

``checks()`` returns the table and tests/test_reproductions.py asserts every verdict, so the tests are
the single place where these comparisons are checked (redundancy audit, item 6); this script only
writes outputs/walmsley2024_checks.csv.

Digitised values: pixel analysis of the PDF at 200 dpi, axes calibrated on
tick marks; round-trip accuracy of the method <= 0.03 units at this
resolution (tested on a known curve).
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from pinch import energy_balance, load_streams, problem_table
from pinch.heat_pump import lorenz_cop
from pinch.validation import ROOT

FIG8 = {"Q_D_MW": 3.54, "Q_S_MW": 0.46}                       # published (Fig. 8)
TEXT_PINCH_RANGE_C = (5.5, 10.5)                              # published (Sec. 4.2)
SIMPLE_DESIGN = {"T_source_C": 15.0, "T_sink_C": 105.0, "eta": 0.5, "COP": 2.1}  # published (Sec. 4.2.3)
FIG11_SIMPLE_W_MW = 2.00                                      # digitised (Fig. 11)
SPRAY_PUBLISHED = {"Qh_MW": 4.98, "Qc_MW": 3.99}              # published (Sec. 4.1, Fig. 5)
SPRAY_INFERRED = {"Exhaust 2 end_C": 23.0, "VF bed start_C": 25.0}  # inferred from Fig. 5


def checks() -> pd.DataFrame:
    """Every check as a row: check, quantity, value, reference, verdict."""
    rows = []

    def record(check, quantity, value, reference, verdict):
        rows.append({"check": check, "quantity": quantity, "value": value, "reference": reference, "verdict": verdict})
        print(f"[{check}] {quantity}: {value}  (reference: {reference})  -> {verdict}")

    evap = load_streams(ROOT / "data" / "walmsley2024_milk_evaporator.csv")
    t = problem_table(evap)
    record("W1", "Qh_min / Qc_min [MW]", f"{t.Qh_min / 1000:.3f} / {t.Qc_min / 1000:.3f}",
           f"{FIG8['Q_D_MW']} / {FIG8['Q_S_MW']} (Fig. 8)",
           "reproduced" if abs(t.Qh_min / 1000 - FIG8["Q_D_MW"]) < 0.005 and abs(t.Qc_min / 1000 - FIG8["Q_S_MW"]) < 0.005
           else "NOT reproduced")

    record("W2", "pinch boundaries T* [°C], Table 2 shifts", t.pinch_T_star_C, f"range {TEXT_PINCH_RANGE_C} (text)",
           "matches text" if (min(t.pinch_T_star_C), max(t.pinch_T_star_C)) == TEXT_PINCH_RANGE_C
           else "lower bound differs")
    chiller_25 = replace(evap, streams=tuple(replace(s, dT_shift_K=2.5) if s.name == "Chiller Water" else s
                                             for s in evap.streams))
    t25 = problem_table(chiller_25)
    record("W2", "pinch boundaries T* [°C], chiller dT_cont = 2.5 K", t25.pinch_T_star_C, f"{TEXT_PINCH_RANGE_C}",
           "matches text; targets unchanged" if (min(t25.pinch_T_star_C), max(t25.pinch_T_star_C)) == TEXT_PINCH_RANGE_C
           and abs(t25.Qh_min - t.Qh_min) < 1e-9 else "does not match")

    cop = lorenz_cop(SIMPLE_DESIGN["T_sink_C"], SIMPLE_DESIGN["T_sink_C"],
                     SIMPLE_DESIGN["T_source_C"], SIMPLE_DESIGN["T_source_C"], SIMPLE_DESIGN["eta"])
    record("W3", "simple-design COP", round(cop, 3), f"{SIMPLE_DESIGN['COP']} (text)",
           "reproduced" if abs(cop - SIMPLE_DESIGN["COP"]) < 0.05 else "NOT reproduced")

    W_target = t.Qh_min / cop / 1000
    record("W4", "simple design W = Qh_min / COP [MW]", round(W_target, 3), f"{FIG11_SIMPLE_W_MW} (Fig. 11, digitised)",
           f"{100 * (W_target - FIG11_SIMPLE_W_MW) / FIG11_SIMPLE_W_MW:+.0f} %: marker is a practical design "
           "(Lincoln et al.), not a target")

    spray = load_streams(ROOT / "data" / "walmsley2024_spray_dryer.csv")
    ts = problem_table(spray)
    bal = energy_balance(spray)
    record("W5", "Qc - Qh from Table 1 (first law) [MW]", round(bal["net_surplus"] / 1000, 3),
           f"{SPRAY_PUBLISHED['Qc_MW'] - SPRAY_PUBLISHED['Qh_MW']:.2f} from published targets",
           "INCONSISTENT: published targets cannot come from Table 1"
           if abs(bal["net_surplus"] / 1000 - (SPRAY_PUBLISHED["Qc_MW"] - SPRAY_PUBLISHED["Qh_MW"])) > 0.05 else "consistent")
    record("W5", "Qh_min / Qc_min from Table 1 [MW]", f"{ts.Qh_min / 1000:.3f} / {ts.Qc_min / 1000:.3f}",
           f"{SPRAY_PUBLISHED['Qh_MW']} / {SPRAY_PUBLISHED['Qc_MW']}",
           "reproduced" if _close_3sf(ts, SPRAY_PUBLISHED) else "differs")

    variant = []
    for s in spray.streams:
        if s.name.startswith("Exhaust 2"):
            T_end = SPRAY_INFERRED["Exhaust 2 end_C"]
            s = replace(s, T_out_C=T_end, Q=s.CP * (s.T_in_C - T_end))
        if s.name.startswith("Vibrating"):
            s = replace(s, T_in_C=SPRAY_INFERRED["VF bed start_C"])  # load kept as published
        variant.append(s)
    tv = problem_table(replace(spray, streams=tuple(variant)))
    record("W6", "Qh_min / Qc_min, inferred variant [MW]", f"{tv.Qh_min / 1000:.3f} / {tv.Qc_min / 1000:.3f}",
           f"{SPRAY_PUBLISHED['Qh_MW']} / {SPRAY_PUBLISHED['Qc_MW']}",
           (f"matches to 3 s.f.; pinch T* {tv.pinch_T_star_C} (Fig. 5B about 32 °C). Inferred, not published"
            if _close_3sf(tv, SPRAY_PUBLISHED) else "does not match"))

    return pd.DataFrame(rows)


def _close_3sf(table, published: dict) -> bool:
    """Q̇h,min and Q̇c,min equal to the published MW values at three significant figures."""
    return (f"{table.Qh_min / 1000:.3g}" == f"{published['Qh_MW']:.3g}"
            and f"{table.Qc_min / 1000:.3g}" == f"{published['Qc_MW']:.3g}")


def main() -> None:
    out = ROOT / "outputs"
    out.mkdir(exist_ok=True)
    checks().to_csv(out / "walmsley2024_checks.csv", index=False)


if __name__ == "__main__":
    main()
