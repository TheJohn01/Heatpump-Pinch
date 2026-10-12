"""Verification of the step-4a assumptions (Padullés et al., 2026, brewery case).

Each check prints a verdict and writes outputs/step4_assumption_checks.csv.

A1  Source temperature -1 °C for all units: compare the published COPs with
    the COPs implied by the temperatures drawn in Fig. 12 (digitised), and
    bound the effect of an ambient source.
A2  Utility temperatures read directly on the T* axis, isothermal units over
    1 K: sensitivity of the minimum-energy design to the isothermal width.
A3  HTHP sink at 103 °C: compare with the 107 °C drawn in Fig. 12.
A4  Fig. 11 values: digitised from the figure pixels (300 dpi) instead of
    being read by eye; compare the full curves.
A5  Source accounting: re-absorbed surplus equals unused sink heat.

Digitised values (pixel analysis of the PDF figures at 300 dpi, axis
calibrated on the gridlines; resolution about 0.05 kWh/hl and 0.2 K):
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pinch import load_streams, problem_table
from pinch.heat_pump import HeatPump, integrate, max_useful_sink_duty
from pinch.validation import ROOT

ETA = 0.55          # published, Sec. 4.3.1
T_COLD_C = -1.0     # published, Sec. 4.1 (GCC minimum T*)

# Fig. 11, solid lines, digitised [kWh/hl] at steam temperature [°C]
FIG11_WITH_HR = {100: 5.52, 110: 5.97, 120: 6.42, 140: 7.23, 160: 7.96, 180: 8.59}
FIG11_NO_HR = {100: 11.88, 110: 12.75, 120: 13.62, 140: 15.22, 160: 16.70, 180: 18.02}
FIG11_EB_REF = {"with_HR": 11.00, "no_HR": 22.73}  # dashed lines
# Fig. 12, digitised T* [°C] and duty ranges [kWh/hl]
FIG12 = {"HTHP_condenser_T": 107.1, "HTHP_condenser_Q": (7.94, 11.35),
         "CO2_gas_cooler_T": (22.3, 79.0), "cooling_source_T": -5.6, "cooling_source_Q": (0.03, 3.87),
         "ambient_source_T": 10.9, "ambient_source_Q": (3.75, 8.41)}

OUT = ROOT / "outputs"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    streams = load_streams(ROOT / "data" / "brewery_streams.csv")
    base = problem_table(streams)
    rows = []

    def record(check, quantity, value, reference, verdict):
        rows.append({"check": check, "quantity": quantity, "value": value,
                     "reference": reference, "verdict": verdict})
        print(f"[{check}] {quantity}: {value}  (reference: {reference})  -> {verdict}")

    # A1 -------------------------------------------------------------
    co2_pub = HeatPump("CO2", 8.3, 18, 82, T_COLD_C, T_COLD_C, eta_lorenz=ETA)
    co2_fig12 = HeatPump("CO2", 8.3, FIG12["CO2_gas_cooler_T"][0], FIG12["CO2_gas_cooler_T"][1],
                         FIG12["cooling_source_T"], FIG12["cooling_source_T"], eta_lorenz=ETA)
    co2_ambient = HeatPump("CO2", 8.3, 18, 82, FIG12["ambient_source_T"], FIG12["ambient_source_T"], eta_lorenz=ETA)
    record("A1", "CO2 HP COP, source -1 °C (our assumption)", round(co2_pub.COP, 3), "3.5 published; 3.46 from Fig. 14",
           "matches")
    record("A1", "CO2 HP COP, temperatures drawn in Fig. 12", round(co2_fig12.COP, 3), "3.5 published",
           "does not match: Fig. 12 is schematic")
    record("A1", "CO2 HP W, all source at -1 °C [kWh/hl]", round(co2_pub.W, 3), "2.4 (Fig. 14)", "upper bound")
    record("A1", "CO2 HP W, all source ambient at 10.9 °C [kWh/hl]", round(co2_ambient.W, 3), "-",
           "lower bound (needs a separate evaporator)")

    # A2 -------------------------------------------------------------
    for w in (0.25, 0.5, 1.0, 2.0):
        co2 = HeatPump("CO2 HP", 1.0, 18, 82, T_COLD_C, T_COLD_C, eta_lorenz=ETA, isothermal_width_K=w)
        Q_co2 = max_useful_sink_duty(streams, co2)
        hthp = HeatPump("HTHP", base.Qh_min - Q_co2, base.T_star_C[0], base.T_star_C[0], T_COLD_C, T_COLD_C,
                        eta_lorenz=ETA, isothermal_width_K=w)
        r = integrate(streams, [co2.with_sink_duty(Q_co2), hthp])
        record("A2", f"min-energy design W_total, width {w} K [kWh/hl]",
               round(Q_co2 / co2.COP + hthp.W, 4), "3.44 (width 1 K)",
               f"Qh_after {r.Qh_after:.3f}; external source {sum(r.Q_source_external.values()):.3f}")

    # A3 -------------------------------------------------------------
    for T_sink in (103.0, FIG12["HTHP_condenser_T"]):
        hthp = HeatPump("HTHP", 2.4, T_sink, T_sink, T_COLD_C, T_COLD_C, eta_lorenz=ETA)
        record("A3", f"HTHP COP / W at sink {T_sink} °C", f"{hthp.COP:.3f} / {hthp.W:.3f}",
               "COP 2.0, W 1.2 (Sec. 4.3.2, Fig. 14)",
               "matches" if abs(hthp.W - 1.2) < 0.02 else f"W off by {hthp.W - 1.2:+.3f}")

    # A4 -------------------------------------------------------------
    for label, fig, Q in (("with HR", FIG11_WITH_HR, 11.3), ("no HR", FIG11_NO_HR, 21.4)):
        devs = []
        for T, W_fig in fig.items():
            W = HeatPump("CCHS", Q, T, T, T_COLD_C, T_COLD_C, eta_lorenz=ETA).W
            devs.append(100 * (W - W_fig) / W_fig)
        record("A4", f"Fig. 11 {label}: deviation range over 100-180 °C [%]",
               f"{min(devs):+.1f} to {max(devs):+.1f}", "digitised curve",
               "reproduced" if max(abs(d) for d in devs) < 5 else "not reproduced")
    record("A4", "Fig. 11 'EB + Ref. with HR' [kWh/hl]", FIG11_EB_REF["with_HR"],
           "electric boiler alone needs >= 11.3", "inconsistent with the 11.3 kWh/hl heat demand used elsewhere")

    # A5 -------------------------------------------------------------
    cchs = HeatPump("CCHS", 11.3, 103, 103, T_COLD_C, T_COLD_C, eta_lorenz=ETA)
    r = integrate(streams, [cchs])
    record("A5", "Re-absorbed surplus vs unused sink heat [kWh/hl]",
           f"{r.Q_source_recirculated:.4f} vs {r.Q_sink_excess:.4f}", "equal by first law",
           "equal" if abs(r.Q_source_recirculated - r.Q_sink_excess) < 1e-6 else "NOT equal")
    record("A5", "Cold utility replaced [kWh/hl]", round(r.Q_cold_utility_replaced, 4),
           f"Qc_min = {base.Qc_min:.4f}", "equal" if abs(r.Q_cold_utility_replaced - base.Qc_min) < 1e-6 else "differs")

    pd.DataFrame(rows).to_csv(OUT / "step4_assumption_checks.csv", index=False)


if __name__ == "__main__":
    main()
