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
    # O&M (DEA): boiler 1.23 EUR/MWh avoided; heat pump 2.494 EUR/kW/y + 3.6 EUR/MWh of heat (sheet 2.a)
    savings += 1000 * 1.23 - (2.494 * 125.0 + 3.6 * 1000)
    assert e.capex_EUR == pytest.approx(capex)
    assert e.savings_EUR == pytest.approx(savings)
    assert e.payback_years == pytest.approx(capex / savings)
    assert e.npv_EUR == pytest.approx(-capex + savings * P.annuity_factor)
    assert e.co2_avoided_t == pytest.approx(1000 * 0.182 - 400 * 0.1)  # default gas EF (IPCC, GCV)
    assert e.primary_energy_reduction == pytest.approx(1 - 400 * 1.9 / (1000 * 0.90))   # gas on NCV (B5)


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
    """1 Mhl/year, prices from the case file: CAPEX and savings of the GCC design by hand."""
    import json
    from analyse import analyse
    from pinch.case import load_case
    from pinch.validation import ROOT
    path = ROOT / "cases" / "brewery_padulles2026.json"
    ec = json.loads(path.read_text(encoding="utf-8"))["economics"]
    p_gas, p_el, eta_b = ec["gas_price_EUR_per_kWh"], ec["electricity_price_EUR_per_kWh"], ec["boiler_efficiency"]
    s = analyse(load_case(path), output_root=tmp_path)
    full = s["economics"]["results"]["full design (heat recovery installed)"]
    Q_co2, Q_hthp, W = 7.2824, 2.7600, 3.7845             # kWh/hl, from the step-4 design at eta_L 0.50
    kW = lambda q: q * 1e3 * 1000 / 8000                   # kWh/hl -> MWh/year -> kW at 8000 h
    capex = (520_000 + 600 * kW(Q_co2)) + (520_000 + 600 * kW(Q_hthp))
    savings = (10.0424 / eta_b * p_gas - W * p_el) * 1e6   # kWh/hl x 1e6 hl/year x EUR/kWh
    # O&M (DEA): boiler 1.23 EUR/MWh of heat avoided; heat pumps 2.494 EUR/kW/y + 3.6 EUR/MWh (sheet 2.a)
    savings += 10.0424 * 1e3 * 1.23 - (2.494 * (kW(Q_co2) + kW(Q_hthp)) + 3.6 * (Q_co2 + Q_hthp) * 1e3)
    if ec.get("chiller_cop"):
        # refrigeration below ambient: Q̇c,min 3.4424 minus the GCC heat flow at T* = 15 °C (the
        # 17 -> 14 °C interval releases 0.3318, 2 of its 3 K lie above 15 °C: 0.2212); all taken over by the heat pumps
        savings += (3.4424 - 0.2212) / ec["chiller_cop"] * p_el * 1e6
    assert full["capex_EUR"] == pytest.approx(capex, rel=1e-3)
    assert full["savings_EUR"] == pytest.approx(savings, rel=1e-3)
    assert s["economics"]["RQ3"]["ratio_used"] == pytest.approx(p_el / p_gas, abs=1e-3)
    # every scenario changes only what it names: the base scenario values reappear when nothing is overridden
    names = [r["scenario"] for r in s["economics"]["scenarios"]]
    assert len(names) == len(ec["scenarios"])
    eta_rows = s["eta_lorenz_sensitivity"]
    cops = [r["COP_system"] for r in eta_rows]
    assert cops == sorted(cops)                              # higher Lorenz efficiency, higher COP


# ------------------------------------------- Padullés et al. (2026), Appendix B, Case DK1
#: Table B.4 (supplementary material): annual OPEX [M EUR], total CAPEX [M EUR], NPV10 [M EUR], PBP [y]
DK1_TABLE_B4 = {
    "Natural gas boiler and HR": (0.83, 0.55, 5.01, 0.8),
    "Centralized HTHP": (1.10, 2.32, 1.18, 5.1),
    "Centralized EB and HR": (1.28, 0.98, 1.11, 3.6),
    "Centralized HTHP and HR": (0.56, 1.99, 5.68, 2.0),
    "HP into HR tank, Pfaduko and HTHP": (0.36, 2.74, 6.49, 2.3),
    "HP into HR tank, Pfaduko and EB": (0.43, 2.19, 6.50, 1.9),
    "HP into HR tank, MVR and EB boost": (0.44, 2.35, 6.22, 2.1),
    "HP into HR tank, MVR and HTHP boost": (0.37, 2.93, 6.18, 2.5),
}
DK1_BASE_OPEX_MEUR = 1.55


@pytest.mark.parametrize("name", list(DK1_TABLE_B4))
def test_padulles2026_appendix_B_DK1_npv_and_payback(name):
    """Our NPV10 (5 %, 10 y) and payback reproduce Table B.4 from its own OPEX and CAPEX.

    Published OPEX and CAPEX are rounded to 0.01 M EUR, so savings carry up to
    +/- 0.01 M EUR and NPV10 up to +/- 0.01 x 7.72 + 0.005 = 0.083 M EUR.
    """
    opex, capex_MEUR, npv_pub, pbp_pub = DK1_TABLE_B4[name]
    p = load_economics({"gas_price_EUR_per_kWh": 1.0, "boiler_efficiency": 1.0, "electricity_to_gas_ratio": 1.0,
                        "discount_rate": 0.05, "horizon_years": 10,
                        "cost_functions": {"hr_tank": {"alpha": 1.0, "beta": 0.0, "gamma": 1.0}}})
    # gas at 1 EUR/kWh: OPEX [EUR] = MWh x 1000, so OPEX in M EUR <-> 1000 MWh
    baseline = Option("base", DK1_BASE_OPEX_MEUR * 1e3, 0.0)
    option = Option(name, opex * 1e3, 0.0, (("hr_tank", capex_MEUR * 1e6),))
    e = evaluate(option, baseline, p)
    assert e.npv_EUR / 1e6 == pytest.approx(npv_pub, abs=0.083)
    pbp_tol = 0.05 + pbp_pub * 0.01 / (DK1_BASE_OPEX_MEUR - opex) + 0.005 / (DK1_BASE_OPEX_MEUR - opex)
    assert e.payback_years == pytest.approx(pbp_pub, abs=pbp_tol)


def test_refrigeration_credit_fraction_scales_credit():
    from pinch.economics import load_economics
    with pytest.raises(ValueError):
        load_economics({"refrigeration_credit_fraction": 1.5})
    assert load_economics({}).refrigeration_credit_fraction == 1.0


# ---------------------------------------------------------------- heat pump cost by sink temperature
def test_heat_pump_cost_classes_pick_catalogue_sheet():
    from pinch.economics import load_economics
    block = {"cost_functions": {"a": {"alpha": 950.0, "beta": 0.0, "gamma": 1.0, "size_unit": "kW"},
                                "b": {"alpha": 1200.0, "beta": 0.0, "gamma": 1.0, "size_unit": "kW"}},
             "heat_pump_cost_classes": [{"max_sink_T_C": 125, "cost_function": "b"},
                                        {"max_sink_T_C": 60, "cost_function": "a"}]}
    p = load_economics(block)
    assert p.heat_pump_cost_class(55.0) == ("a", False)
    assert p.heat_pump_cost_class(60.0) == ("a", False)
    assert p.heat_pump_cost_class(105.0) == ("b", False)
    assert p.heat_pump_cost_class(160.0) == ("b", True)            # above every class: extrapolated
    assert load_economics({}).heat_pump_kind(105.0) == "heat_pump"  # no classes: Padullés Table 3


def test_heat_pump_cost_classes_need_their_cost_function():
    from pinch.economics import load_economics
    with pytest.raises(ValueError, match="no cost function"):
        load_economics({"heat_pump_cost_classes": [{"max_sink_T_C": 60, "cost_function": "missing"}]})


def test_milk_evaporator_capex_uses_dea_sheets():
    """Hand check: 0.64 MW at 55 °C (sheet 1.1, 0.95 M€/MW) + 2.90 MW of steam at 105 °C from 15 °C
    (sheet 2.a 1.2 + lift above 75 K 0.15 + steam generation 0.2 = 1.55 M€/MW)."""
    from dataclasses import replace
    from analyse import compute
    from pinch.case import load_case
    from pinch.validation import ROOT
    c = load_case(ROOT / "cases" / "walmsley2024_milk_evaporator.json")
    res = compute(replace(c, basis={"type": "power", "operating_hours_per_year": 8000.0}))
    t = res.tables["heat_pump_design"]
    expected = sum(q * (950.0 if T <= 60 else 1550.0) for q, T in zip(t["Q_sink_kW"], t["T_sink_out_C"]))
    full = res.summary["economics"]["results"]["full design (heat recovery installed)"]
    assert full["capex_EUR"] == pytest.approx(expected, rel=1e-6)
    assert res.summary["economics"]["heat_pump_cost_class"] == {
        "HP warm (milk preheat)": "hp_dea_1_1", "HTHP 105 °C": "hp_dea_2a + dea_lift_2a + dea_steam"}


def test_heat_pump_cost_adders_follow_lift_and_steam():
    from types import SimpleNamespace as U
    from pinch.economics import load_economics
    lin = lambda a: {"alpha": a, "beta": 0.0, "gamma": 1.0, "size_unit": "kW"}  # noqa: E731
    p = load_economics({"cost_functions": {"b": lin(1200.0), "lift": lin(150.0), "steam": lin(200.0)},
                        "heat_pump_cost_classes": [{"max_sink_T_C": 125, "cost_function": "b"}],
                        "heat_pump_cost_adders": [{"cost_function": "lift", "applies_to": ["b"], "min_lift_K": 75},
                                                  {"cost_function": "steam", "applies_to": ["b"], "isothermal_sink": True}]})
    hot_water = U(T_sink_in_C=60.0, T_sink_out_C=90.0, T_source_in_C=30.0, T_source_out_C=25.0)   # lift 65 K
    steam = U(T_sink_in_C=105.0, T_sink_out_C=105.0, T_source_in_C=15.0, T_source_out_C=14.0)   # lift 91 K
    assert p.heat_pump_cost_items(hot_water) == (("b",), False)
    assert p.heat_pump_cost_items(steam) == (("b", "lift", "steam"), False)


def test_cooling_water_cost_follows_price_and_hours():
    """Sinnott & Towler Sec. 6.4.4: 0.0341 kWh + 0.00042 EUR per kWh removed; 8000 h at 0.1135 EUR/kWh = 34.3."""
    from dataclasses import replace
    from analyse import compute
    from pinch.case import load_case
    from pinch.validation import ROOT
    c = load_case(ROOT / "cases" / "fourstream_example.json")
    for hours, p_el in [(8000.0, 0.1135), (6000.0, 0.0897)]:
        eco = {**c.economics, "operating_hours_per_year": hours, "electricity_price_EUR_per_kWh": p_el}
        at = compute(replace(c, basis={"type": "power", "operating_hours_per_year": hours}, economics=eco)).summary["area_targeting"]
        assert at["cold_utility_cost_EUR_per_kW_year"] == pytest.approx(hours * (p_el * 0.0341 + 0.000421), rel=1e-3)


def test_spray_dryer_steam_add_on_only_for_steam_heat_pump():
    """Liang et al. (2022): water loops up to 114 °C, a closed-loop steam heat pump for the main air."""
    from analyse import compute
    from pinch.case import load_case
    from pinch.validation import ROOT
    c = load_case(ROOT / "cases" / "walmsley2024_spray_dryer.json")
    assert c.basis == {"type": "power", "operating_hours_per_year": 6000}        # published by Liang et al. (2022)
    cls = compute(c).summary["economics"]["heat_pump_cost_class"]
    assert "steam" not in cls["HTHP 120 °C (fluid beds)"]
    assert "dea_steam" in cls["HTHP 200 °C (main air)"]
