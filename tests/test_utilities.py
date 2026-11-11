"""Tests for several utility levels (``pinch.utilities``), the heat pump temperature contribution
(``dT_cont_K``) and working-fluid screening (``pinch.refrigerants``).

Known answers: the Problem Table (one hot and one cold utility), GCC heat flows (a level in a monotonic
part of the GCC), the existing GCC sizing of ``pinch.design`` (brewery sink levels), the Lorenz COP
formula, and the European Commission's restatement of Regulation (EU) 2024/573.
"""

import numpy as np
import pytest

from pinch import load_streams, problem_table
from pinch.case import load_case
from pinch.cycle_analysis import refrigerant_columns
from pinch.design import design_from_gcc
from pinch.heat_pump import HeatPump, lorenz_cop
from pinch.refrigerants import REFRIGERANTS, fgas_issues
from pinch.sensitivity import apply
from pinch.utilities import Utility, utility_targets

BREWERY = "data/brewery_streams.csv"


def _gcc(table, T):
    return float(np.interp(T, table.T_star_C[::-1], table.cascade_feasible[::-1]))


@pytest.mark.parametrize("name", ["four_stream_process_streams.csv", "brewery_streams.csv",
                                  "milk_evaporator_streams.csv", "northwestern_4stream.csv"])
def test_one_hot_one_cold_utility_give_the_problem_table(name):
    s = load_streams("data/" + name)
    t = problem_table(s)
    hi, lo = float(t.T_star_C[0]) + 50, float(t.T_star_C[-1]) - 50
    r = utility_targets(s, [Utility("steam", "hot", hi, hi, 1.0), Utility("cw", "cold", lo, lo, 0.1)])
    assert r.loads["steam"] == pytest.approx(t.Qh_min, abs=1e-9 * max(1, t.Qh_min))
    assert r.loads["cw"] == pytest.approx(t.Qc_min, abs=1e-9 * max(1, t.Qh_min))


@pytest.mark.parametrize("T", [40.0, 60.0])
def test_cheap_level_in_a_monotonic_gcc_takes_the_gcc_heat_flow(T):
    """Brewery GCC falls monotonically from 57 to 17 °C T* and rises to 77 °C: an isothermal hot level at T
    (spread over T-1..T) can supply exactly the GCC heat flow at T; steam supplies the rest."""
    s = load_streams(BREWERY)
    t = problem_table(s)
    r = utility_targets(s, [Utility("hw", "hot", T, T, 1.0), Utility("steam", "hot", 180, 180, 5.0),
                            Utility("cw", "cold", -20, -20, 1.0)])
    assert r.loads["hw"] == pytest.approx(_gcc(t, T), abs=1e-9)
    assert r.total_hot == pytest.approx(t.Qh_min)


def test_pocket_limits_a_level_below_it():
    """At 80 °C the GCC carries 9.39 kWh/hl, but the pocket at 98-102 °C T* (minimum 7.28 at 99 °C) means
    any level below it can supply at most 7.28: steam must cover 10.04 - 7.28 = 2.76 above."""
    s = load_streams(BREWERY)
    r = utility_targets(s, [Utility("hw", "hot", 80, 80, 1.0), Utility("steam", "hot", 180, 180, 5.0),
                            Utility("cw", "cold", -20, -20, 1.0)])
    assert r.loads["hw"] == pytest.approx(7.282353, abs=1e-5)
    assert r.loads["steam"] == pytest.approx(2.76, abs=1e-5)


def test_brewery_sink_levels_match_the_gcc_design():
    """The case's own levels (warm water 18 -> 82 °C, steam at the GCC top, 103 °C) as utilities, cheapest
    lowest: the same duties as ``design_from_gcc``."""
    c = load_case("cases/brewery.json")
    s = load_streams(c.stream_file)
    d = {u.name: u.Q_sink for u in design_from_gcc(s, c.sink_levels, c.eta_lorenz, c.source_T_C).units}
    r = utility_targets(s, [Utility("Warm-water HP", "hot", 82, 18, 1.0), Utility("HTHP", "hot", 103, 103, 2.0),
                            Utility("cw", "cold", -5, -5, 0.1)])
    assert r.loads["Warm-water HP"] == pytest.approx(d["Warm-water HP"], abs=1e-6)
    assert r.loads["HTHP"] == pytest.approx(d["HTHP (wort boiling)"], abs=1e-6)


def test_utilities_that_cannot_close_the_cascade():
    s = load_streams(BREWERY)
    with pytest.raises(ValueError, match="cannot close"):
        utility_targets(s, [Utility("hw", "hot", 60, 60, 1.0), Utility("cw", "cold", -20, -20, 1.0)])
    with pytest.raises(ValueError):
        Utility("x", "hot", 50, 80, 1.0)


# ---------------------------------------------------------------- heat pump temperature contribution
def test_dT_cont_moves_the_cop_temperatures_only():
    """COP at sink + dT and source - dT (Lorenz formula); duty and cascade position unchanged."""
    hp = HeatPump("x", 1.0, 18.0, 82.0, -1.0, -1.0, eta_lorenz=0.5)
    hp2 = HeatPump("x", 1.0, 18.0, 82.0, -1.0, -1.0, eta_lorenz=0.5, dT_cont_K=2.0)
    assert hp.COP == pytest.approx(lorenz_cop(18, 82, -1, -1, 0.5))
    assert hp2.COP == pytest.approx(lorenz_cop(20, 84, -3, -3, 0.5))
    assert hp2.COP < hp.COP
    with pytest.raises(ValueError):
        HeatPump("x", 1.0, 18.0, 82.0, -1.0, -1.0, eta_lorenz=0.5, dT_cont_K=-1.0)


def test_dT_cont_zero_reproduces_the_case_and_the_sensitivity_row_lowers_cop():
    c = load_case("cases/brewery.json")
    s = load_streams(c.stream_file)
    base = design_from_gcc(s, c.sink_levels, c.eta_lorenz, c.source_T_C)
    loop = design_from_gcc(s, apply(c, "hp_dT_cont", 2.0).sink_levels, c.eta_lorenz, c.source_T_C)
    assert [u.Q_sink for u in loop.units] == pytest.approx([u.Q_sink for u in base.units])
    assert all(a.COP < b.COP for a, b in zip(loop.units, base.units))
    assert base.units[0].COP == pytest.approx(3.225, abs=1e-3)     # warm-water HP at eta_L 0.50, published base


# ---------------------------------------------------------------- refrigerants
def test_hydrocarbons_and_natural_refrigerants_are_outside_the_prohibitions():
    for f in ("n-Propane", "n-Butane", "Ammonia", "CarbonDioxide", "Water", "n-Pentane / Ammonia"):
        assert fgas_issues(f, 3000, 2035) == []


def test_annex_iv_dates_and_limits():
    """EC restatement of Annex IV: self-contained > 50 kW, GWP >= 150 from 2030; split > 12 kW, GWP >= 750
    from 2029 and >= 150 from 2033. Low-GWP HFOs pass; a GWP-675 fluid (R-32 on the EC page) does not."""
    assert fgas_issues("R1234ze(E)", 3000, 2035) == []
    assert fgas_issues("R1233zd(E)", 3000, 2035, "split") == []
    from pinch.refrigerants import Refrigerant
    REFRIGERANTS["_R32"] = Refrigerant("_R32", "R-32", True, 675.0, "A2L")
    try:
        assert fgas_issues("_R32", 3000, 2029) == []
        assert fgas_issues("_R32", 3000, 2030)
        assert fgas_issues("_R32", 30, 2027)                       # 12-50 kW self-contained from 2027
        assert fgas_issues("_R32", 3000, 2032, "split") == []      # 675 < 750
        assert fgas_issues("_R32", 3000, 2033, "split")
    finally:
        del REFRIGERANTS["_R32"]
    assert "unknown" in fgas_issues("SomethingElse", 3000, 2030)[0]


def test_refrigerant_columns_for_a_cascade():
    c = refrigerant_columns("Ammonia / R1233zd(E)")
    assert c == {"GWP100": "0 / 3.88", "safety_group": "B2L / A1", "F_gas": "no / yes"}
    assert refrigerant_columns("n-Butane")["GWP100"] == ""
