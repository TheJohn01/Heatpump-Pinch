"""Tests for the economics (workflow step 6).

1. Building blocks against hand calculations (cost functions, annuity, payback,
   CO2, primary energy, break-even ratio).
2. Paper reproduction: the four qualitative statements of Padullés et al.
   (2026), Sec. 5.2.
3. The general analysis on the brewery case against a hand calculation.
"""

import math

import pytest

from pinch.economics import CostFunction, Option, break_even_ratio, capacity_kW, evaluate, load_economics

P = load_economics({"gas_price_EUR_per_kWh": 0.06, "electricity_to_gas_ratio": 2.0, "boiler_efficiency": 1.0,
                    "operating_hours_per_year": 8000, "discount_rate": 0.05, "horizon_years": 10,
                    "grid_EF_kg_per_kWh": 0.1, "co2_price_EUR_per_t": 0})


# ---------------------------------------------------------- building blocks
def test_cost_functions_table3():
    """Padullés et al. (2026) Table 3: HP 600 EUR/kW + 520,000 EUR; tank 7450 V^0.65."""
    assert P.cost_functions["heat_pump"].cost(1000) == pytest.approx(1_120_000)
    assert P.cost_functions["hr_tank"].cost(100) == pytest.approx(7450 * 100 ** 0.65)
    assert P.cost_functions["mvr"].cost(0) == 0.0


def test_annuity_factor():
    assert P.annuity_factor == pytest.approx((1 - 1.05 ** -10) / 0.05)  # 7.7217


def test_evaluate_hand_calculation():
    """1000 MWh/year heat moved from gas to a COP-2.5 heat pump."""
    base = Option("base", 1000.0, 0.0)
    hp = Option("hp", 0.0, 400.0, (("heat_pump", capacity_kW(1000.0, P)),))
    e = evaluate(hp, base, P)
    capex = 520_000 + 600 * 125.0
    savings = 1000 * 60 - 400 * 120          # EUR/year: gas at 60, electricity at 120 EUR/MWh
    assert e.capex_EUR == pytest.approx(capex)
    assert e.savings_EUR == pytest.approx(savings)
    assert e.payback_years == pytest.approx(capex / savings)
    assert e.npv_EUR == pytest.approx(-capex + savings * P.annuity_factor)
    assert e.co2_avoided_t == pytest.approx(1000 * 0.219 - 400 * 0.1)
    assert e.primary_energy_reduction == pytest.approx(1 - 400 * 1.9 / 1000)


def test_boiler_efficiency_scales_fuel():
    base = Option("base", 900.0, 0.0)
    p = load_economics({"boiler_efficiency": 0.9})
    e = evaluate(Option("none", 900.0, 0.0), base, p)
    assert e.gas_fuel_MWh == pytest.approx(1000.0)


def test_break_even_ratio_gives_zero_npv():
    """10,000 MWh/year at COP 2.5: break-even ratios are 1.81 (NPV) and 1.44 (5-year payback)."""
    base = Option("base", 10_000.0, 0.0)
    hp = Option("hp", 0.0, 4_000.0, (("heat_pump", 1250.0),))
    r = break_even_ratio(hp, base, P, "npv")
    assert evaluate(hp, base, P.with_ratio(r)).npv_EUR == pytest.approx(0.0, abs=1e-6)
    r_pbp = break_even_ratio(hp, base, P, "payback")
    assert evaluate(hp, base, P.with_ratio(r_pbp)).payback_years == pytest.approx(P.payback_threshold_years)


def test_rejects_bad_parameters():
    with pytest.raises(ValueError):
        load_economics({"boiler_efficiency": 0})
    with pytest.raises(ValueError):
        CostFunction(1, 0, 1).cost(-1)


# ------------------------------------------------------- paper reproduction
def test_padulles_statements_reproduced():
    """Sec. 5.2, S1-S4: run the reproduction and require every statement to hold."""
    import pandas as pd
    import reproduce_padulles2026_economics as rep
    rep.main()
    checks = pd.read_csv(rep.OUT / "step6_padulles_checks.csv")
    assert checks["reproduced"].all(), checks[~checks["reproduced"]].to_string()


# --------------------------------------------------- general analysis (brewery)
def test_brewery_full_design_hand_check(tmp_path):
    """1 Mhl/year, Portugal H1 2025 prices: CAPEX and savings of the GCC design by hand."""
    from analyse import analyse
    from pinch.case import load_case
    from pinch.validation import ROOT
    s = analyse(load_case(ROOT / "cases" / "brewery_padulles2026.json"), output_root=tmp_path)
    full = s["economics"]["results"]["full design (heat recovery installed)"]
    Q_co2, Q_hthp, W = 7.2819, 2.7605, 3.4404             # kWh/hl, from the step-4 design
    kW = lambda q: q * 1e3 * 1000 / 8000                   # kWh/hl -> MWh/year -> kW at 8000 h
    capex = (520_000 + 600 * kW(Q_co2)) + (520_000 + 600 * kW(Q_hthp))
    savings = 10.0424 * 1e3 * 55 - W * 1e3 * 132          # MWh/year x EUR/MWh
    assert full["capex_EUR"] == pytest.approx(capex, rel=1e-3)
    assert full["savings_EUR"] == pytest.approx(savings, rel=1e-3)
    assert s["economics"]["RQ3"]["ratio_used"] == pytest.approx(0.132 / 0.055, abs=1e-3)
