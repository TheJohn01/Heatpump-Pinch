"""Tests for the investment-grade additions (``pinch.investment``) and the input checks added with them.

Known answers: hand calculations, the published tables the constants come from, and the existing
``pinch.economics`` results (the new functions must agree with them where they overlap).
"""

import math

import numpy as np
import pandas as pd
import pytest

from pinch import investment as inv
from pinch.economics import Option, capacity_kW, evaluate, load_economics
from pinch.streams import streams_from_frame

P = load_economics({"gas_price_EUR_per_kWh": 0.06, "electricity_to_gas_ratio": 2.0, "boiler_efficiency": 1.0,
                    "operating_hours_per_year": 8000, "discount_rate": 0.05, "horizon_years": 10})
BASE = Option("base", 1000.0, 0.0)
HP = Option("hp", 0.0, 400.0, (("heat_pump", capacity_kW(1000.0, P)),))


# ---------------------------------------------------------------- cash flows, NPV, IRR
def test_npv_matches_annuity_formula():
    """Constant savings: NPV of the cash flows equals -I + S x annuity factor (pinch.economics)."""
    ev = evaluate(HP, BASE, P)
    flows = inv.cash_flows(ev.capex_EUR, ev.savings_EUR, P.horizon_years)
    assert inv.npv(flows, P.discount_rate) == pytest.approx(ev.npv_EUR, rel=1e-12)


def test_irr_hand_calculation():
    """-1000 then 3 x 500: NPV = 0 at 23.375 % (root of 2 = (1 - (1+r)^-3) / r)."""
    r = inv.irr([-1000.0, 500.0, 500.0, 500.0])
    assert r == pytest.approx(0.23375, abs=1e-5)
    assert inv.npv([-1000.0, 500.0, 500.0, 500.0], r) == pytest.approx(0.0, abs=1e-6)


def test_irr_undefined_without_sign_change():
    assert math.isnan(inv.irr([-1000.0, -10.0, -10.0]))
    assert math.isnan(inv.irr([0.0, 10.0, 10.0]))


def test_discounted_payback():
    assert inv.discounted_payback_years([-1000.0, 500.0, 500.0, 500.0], 0.0) == pytest.approx(2.0)
    # at 10 %: 454.55 + 413.22 = 867.77 after 2 y; 132.23 / 375.66 of year 3
    assert inv.discounted_payback_years([-1000.0, 500.0, 500.0, 500.0], 0.10) == pytest.approx(2.352, abs=1e-3)
    assert inv.discounted_payback_years([-1000.0, 100.0, 100.0], 0.05) == math.inf


def test_tax_and_depreciation_hand_calculation():
    """I = 1000, S = 300, 25 % tax, 5-year straight line: years 1-5 300 - 0.25 (300 - 200) = 275; then 225."""
    flows = inv.cash_flows(1000.0, 300.0, 7, tax_rate=0.25, depreciation_years=5)
    assert flows[0] == -1000.0
    assert flows[1:6] == pytest.approx([275.0] * 5)
    assert flows[6:] == pytest.approx([225.0] * 2)


def test_grant_reduces_outlay_and_depreciable_base():
    flows = inv.cash_flows(1000.0, 300.0, 5, grant_EUR=300.0, tax_rate=0.25, depreciation_years=5)
    assert flows[0] == -700.0
    assert flows[1] == pytest.approx(300.0 - 0.25 * (300.0 - 140.0))


def test_cash_flow_input_checks():
    with pytest.raises(ValueError):
        inv.cash_flows(1000.0, 300.0, 5, tax_rate=0.25)            # depreciation period missing
    with pytest.raises(ValueError):
        inv.cash_flows(1000.0, 300.0, 5, grant_EUR=1500.0)


# ---------------------------------------------------------------- AACE 18R-97, Table 1
def test_aace_table_1():
    assert inv.capex_factors(5, "widest") == pytest.approx((0.50, 2.00))
    assert inv.capex_factors(5, "narrowest") == pytest.approx((0.80, 1.30))
    assert inv.capex_factors(3, "widest") == pytest.approx((0.80, 1.30))
    assert inv.capex_factors(1, "narrowest") == pytest.approx((0.97, 1.03))
    for cls in range(1, 5):                                          # accuracy improves with the class number falling
        assert inv.capex_factors(cls, "widest")[1] <= inv.capex_factors(cls + 1, "widest")[1]
    with pytest.raises(ValueError):
        inv.capex_factors(6)


# ---------------------------------------------------------------- grants
def test_prr_aid_intensity_annex_i():
    assert inv.prr_aid_intensity() == pytest.approx(0.30)
    assert inv.prr_aid_intensity("energy_efficiency", "small", "a") == pytest.approx(0.65)
    assert inv.prr_aid_intensity("environmental_protection", "medium", "c") == pytest.approx(0.55)
    with pytest.raises(ValueError):
        inv.prr_aid_intensity("energy_efficiency", "huge")


def test_grant_ceiling():
    assert inv.grant_EUR(1e6, 0.30) == pytest.approx(300e3)
    assert inv.grant_EUR(100e6, 0.30) == pytest.approx(15e6)


def test_mpr_2026_01_conditions():
    assert inv.mpr_2026_01_admissible(1e6, in_eu_ets=False)[0]
    assert not inv.mpr_2026_01_admissible(1e6, in_eu_ets=True)[0]
    assert not inv.mpr_2026_01_admissible(300e3, in_eu_ets=False)[0]


# ---------------------------------------------------------------- uncertainty
def test_three_point_estimate_equations():
    """Towler and Sinnott (2013), Eqs 9.30-9.31, with the Table 9.4 capital range (-20 % / +50 %)."""
    assert inv.three_point_mean(0.8, 1.0, 1.5) == pytest.approx(1.075)
    assert inv.three_point_std(0.8, 1.5) == pytest.approx(0.7 / 2.65)


def _fixed(x):
    return inv.Range(x, x, x)


def test_monte_carlo_degenerate_ranges_reproduce_the_deterministic_result():
    ev = evaluate(HP, BASE, P)
    s = inv.monte_carlo(HP, BASE, P, capex_factor=_fixed(1.0), gas_price_EUR_per_kWh=_fixed(0.06),
                        price_ratio=_fixed(2.0), n=10)
    assert s["npv_EUR"].to_numpy() == pytest.approx(np.full(10, ev.npv_EUR))
    assert s["payback_years"].to_numpy() == pytest.approx(np.full(10, ev.payback_years))


def test_monte_carlo_linear_savings_match_a_direct_evaluation():
    """The linear reconstruction of the savings equals ``evaluate`` at an arbitrary price pair."""
    s = inv.monte_carlo(HP, BASE, P, capex_factor=_fixed(1.3), gas_price_EUR_per_kWh=_fixed(0.045),
                        price_ratio=_fixed(2.7), n=1)
    direct = evaluate(HP, BASE, load_economics({"gas_price_EUR_per_kWh": 0.045, "electricity_to_gas_ratio": 2.7,
                                                "boiler_efficiency": 1.0, "operating_hours_per_year": 8000}))
    assert s["savings_EUR"][0] == pytest.approx(direct.savings_EUR)
    assert s["investment_EUR"][0] == pytest.approx(1.3 * direct.capex_EUR)


def test_monte_carlo_is_deterministic_and_bounded():
    kw = dict(capex_factor=inv.Range(0.5, 1.0, 2.0), gas_price_EUR_per_kWh=inv.Range(0.03, 0.06, 0.12),
              price_ratio=inv.Range(1.3, 2.0, 3.5), n=2000)
    a, b = inv.monte_carlo(HP, BASE, P, seed=1, **kw), inv.monte_carlo(HP, BASE, P, seed=1, **kw)
    pd.testing.assert_frame_equal(a, b)
    assert a["capex_factor"].between(0.5, 2.0).all() and a["price_ratio"].between(1.3, 3.5).all()
    out = inv.summarise(a, P.payback_threshold_years)
    assert 0.0 <= out["prob_npv_positive"] <= 1.0
    assert out["npv_p5_EUR"] <= out["npv_p50_EUR"] <= out["npv_p95_EUR"]


def test_monte_carlo_grant_raises_npv_by_the_grant():
    kw = dict(capex_factor=_fixed(1.0), gas_price_EUR_per_kWh=_fixed(0.06), price_ratio=_fixed(2.0), n=1)
    ev = evaluate(HP, BASE, P)
    with_grant = inv.monte_carlo(HP, BASE, P, grant_fraction=0.30, **kw)["npv_EUR"][0]
    assert with_grant - ev.npv_EUR == pytest.approx(0.30 * ev.capex_EUR)


def test_brewery_investment_check_agrees_with_the_research_questions():
    """scripts/checks/investment_check.py's 'no grant' rows repeat the consolidated RQ results (payback, NPV) for the brewery."""

    from scripts.checks import investment_check
    root = investment_check.ROOT
    df = investment_check.check(root / "cases" / "brewery.json")
    rq_table = pd.read_csv(root / "outputs" / "brewery" / "rq_consolidated.csv")
    base = rq_table.iloc[0]
    hp1 = df[(df["increment"].str.startswith("HP1")) & (df["scenario"] == "no grant")].iloc[0]
    assert hp1["payback_y"] == pytest.approx(base["HP1_incremental_payback_y"], abs=0.01)
    assert hp1["NPV_MEUR"] == pytest.approx(base["HP1_incremental_NPV_MEUR"], abs=0.002)
    assert hp1["IRR"] > 0.05                                        # NPV > 0 at 5 % means IRR above 5 %
    hp2 = df[(df["increment"].str.startswith("HP2")) & (df["scenario"] == "no grant")].iloc[0]
    assert math.isnan(hp2["IRR"]) and hp2["MC_prob_NPV_positive"] < 0.05
    granted = df[(df["increment"].str.startswith("HP1")) & (df["scenario"].str.startswith("grant 30"))].iloc[0]
    assert granted["payback_y"] == pytest.approx(0.70 * hp1["payback_y"], abs=0.02)


# ---------------------------------------------------------------- input checks
def test_unknown_economics_key_is_an_error_with_a_hint():
    with pytest.raises(ValueError, match="discount_rate"):
        load_economics({"discount_rte": 0.10})
    with pytest.raises(ValueError, match="gas_price_EUR_per_kWh"):
        load_economics({"gas_price_EUR_kWh": 0.12})


def test_notes_and_provenance_keys_are_still_accepted():
    p = load_economics({"_note": "x", "sources": {"a": "b"}, "heat_recovery_equipment": [["hr_tank", 1.0]],
                        "discount_rate": 0.08})
    assert p.discount_rate == 0.08


def _table(**override):
    row = {"stream": "s", "type": "hot", "T_in_C": 100.0, "T_out_C": 50.0, "dT_shift_K": 5.0, "Q_kW": 10.0}
    row.update(override)
    return pd.DataFrame([row])


@pytest.mark.parametrize("override, message", [
    ({"Q_kW": float("inf")}, "finite"),
    ({"T_out_C": -400.0}, "absolute zero"),
    ({"T_out_C": 100.0}, "1 K interval"),
])
def test_non_physical_stream_values_are_rejected(override, message):
    with pytest.raises(ValueError, match=message):
        streams_from_frame(_table(**override))
