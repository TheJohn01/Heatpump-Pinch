"""One refrigeration-credit model for steps 5 and 6 (redundancy audit, item 1.2).

1. Hand calculations on a single hot stream (no heat recovery).
2. The three builders agree where they describe the same cooling.
3. Brewery: the model reproduces the previous step-6 numbers (cascade Q̇c reduction capped at the
   refrigeration duty) wherever that model was right, and the retrofit's coolers give the same duty
   as the network evaluation.
4. The case the previous step-6 model got wrong: a source at ambient takes no refrigeration.
"""

import numpy as np
import pytest

from pinch import load_streams, problem_table, with_extra_shift
from pinch.case import load_case
from pinch.design import design_from_gcc, partial_designs
from pinch.heat_pump import HeatPump, integrate
from pinch.network import evaluate_network, load_networks
from pinch.refrigeration import CoolingCascade, refrigeration_taken_over
from pinch.retrofit import network_cooling
from pinch.streams import Stream, StreamSet
from pinch.validation import ROOT

T_AMB = 15.0


def _one_hot_stream() -> StreamSet:
    """Hot stream 20 -> -10 °C, CP 1 kW/K, no shift: 25 kW below ambient (15 °C)."""
    return StreamSet((Stream("H", "hot", 20.0, -10.0, 30.0, 0.0),), "kW", "hand example")


def _unit(T_src_C: float, Q_source_kW: float) -> HeatPump:
    """Isothermal-source heat pump with COP 2 (sink 60 °C), sized to the given source duty."""
    return HeatPump("HP", 2 * Q_source_kW, 60.0, 60.0, T_src_C, T_src_C, cop_fixed=2.0)


# ---------------------------------------------------------- 1. hand calculations
def test_refrigeration_below_ambient_only():
    cooling = CoolingCascade.from_hot_streams(_one_hot_stream(), T_AMB)
    assert cooling.refrigeration == pytest.approx(25.0)


@pytest.mark.parametrize("T_src_C, Q_src, expected", [
    (-10.0, 20.0, 20.0),    # coldest point: limited by the source duty
    (-10.0, 40.0, 25.0),    # limited by the refrigeration duty
    (5.0, 20.0, 10.0),      # only the 10 kW between 5 and 15 °C is accessible; 15 kW below 5 °C remain
    (15.0, 20.0, 0.0),      # at ambient: cooling water would take that heat anyway
    (18.0, 20.0, 0.0),      # above ambient
])
def test_credit_is_limited_by_source_temperature(T_src_C, Q_src, expected):
    cooling = CoolingCascade.from_hot_streams(_one_hot_stream(), T_AMB)
    assert refrigeration_taken_over([_unit(T_src_C, Q_src)], cooling) == pytest.approx(expected)


def test_warmest_source_is_served_first():
    """Warm source (5 °C) can reach 10 kW, cold source (-10 °C) the rest: 10 + 15 = 25 kW in total."""
    cooling = CoolingCascade.from_hot_streams(_one_hot_stream(), T_AMB)
    units = [_unit(-10.0, 20.0), HeatPump("HP warm", 40.0, 60.0, 60.0, 5.0, 5.0, cop_fixed=2.0)]
    assert refrigeration_taken_over(units, cooling) == pytest.approx(25.0)
    assert refrigeration_taken_over(units, cooling, fraction=0.5) == pytest.approx(12.5)


def test_credit_fraction_is_checked():
    cooling = CoolingCascade.from_hot_streams(_one_hot_stream(), T_AMB)
    with pytest.raises(ValueError):
        refrigeration_taken_over([_unit(-10.0, 1.0)], cooling, fraction=1.5)


def test_no_ambient_means_no_refrigeration():
    assert CoolingCascade.from_hot_streams(_one_hot_stream(), None) is None
    assert refrigeration_taken_over([_unit(-10.0, 1.0)], None) == 0.0


# ---------------------------------------------------------- 2. builders agree
def test_cascade_of_hot_streams_equals_hot_stream_builder():
    """With no cold streams, the Problem Table cascade is the no-recovery cooling."""
    s = _one_hot_stream()
    a = CoolingCascade.from_table(problem_table(s), T_AMB)
    b = CoolingCascade.from_hot_streams(s, T_AMB)
    assert a.refrigeration == pytest.approx(b.refrigeration)
    for T in (-10.0, 0.0, 5.0, 15.0):
        u = [_unit(T, 12.0)]
        assert refrigeration_taken_over(u, a) == pytest.approx(refrigeration_taken_over(u, b))


# ---------------------------------------------------------- 3. brewery
CASE = load_case(ROOT / "cases" / "brewery.json")
BREWERY = with_extra_shift(load_streams(CASE.stream_file), CASE.extra_shift_K)


def test_brewery_refrigeration_duty():
    """Q̇c,min minus the GCC heat flow at T* = ambient (15 °C, below the 17 °C pinch): 3.2212 kWh/hl."""
    t = problem_table(BREWERY)
    gcc_at_ambient = float(np.interp(T_AMB, t.T_star_C[::-1], t.cascade_feasible[::-1]))
    cooling = CoolingCascade.from_table(t, CASE.ambient_T_C)
    assert cooling.refrigeration == pytest.approx(t.Qc_min - gcc_at_ambient)
    assert cooling.refrigeration == pytest.approx(3.2212, abs=1e-4)


def test_brewery_step6_unchanged():
    """Previous step-6 model: min(cascade Q̇c reduction, refrigeration duty). Same numbers along the curve,
    because the brewery's sources (-1 °C) sit at the bottom of the cascade."""
    d = design_from_gcc(BREWERY, CASE.sink_levels, CASE.eta_lorenz, CASE.source_T_C)
    cooling = CoolingCascade.from_table(problem_table(BREWERY), CASE.ambient_T_C)
    for _, partial in partial_designs(d.units, 11):
        old = min(integrate(BREWERY, list(partial)).Q_cold_utility_replaced, cooling.refrigeration) if partial else 0.0
        assert refrigeration_taken_over(partial, cooling) == pytest.approx(old, abs=1e-9)


def test_brewery_network_coolers_match_network_evaluation():
    nets = load_networks(CASE.retrofit["network_file_resolved"])
    for net in nets.values():
        res = evaluate_network(BREWERY, net, CASE.ambient_T_C)
        assert network_cooling(BREWERY, res, CASE.ambient_T_C).refrigeration == pytest.approx(res.refrigeration)


def test_hthp_alone_takes_the_refrigeration_in_a_retrofit():
    """Audit 1.2 example ('N1 + HTHP only'): the HTHP evaporates at T* = -1 °C, at or below every refrigerated
    cooler, so it can take the whole 3.22 kWh/hl. The cascade of the network-constrained stream set gave 0 only
    because that set holds no coolers; it is a sizing set, not the cooling side."""
    nets = load_networks(CASE.retrofit["network_file_resolved"])
    res = evaluate_network(BREWERY, nets["N1 condensate into tank"], CASE.ambient_T_C)
    hthp = HeatPump("HTHP", 10.0, 103.0, 103.0, -1.0, -1.0, eta_lorenz=0.5)
    assert hthp.Q_source > res.refrigeration
    taken = refrigeration_taken_over([hthp], network_cooling(BREWERY, res, CASE.ambient_T_C))
    assert taken == pytest.approx(res.refrigeration)


# ---------------------------------------------------------- 4. the corrected case
def test_source_at_ambient_takes_no_refrigeration():
    """Spray dryer (sources at T* = 15 °C = ambient): the previous step-6 model credited the cascade's Q̇c
    reduction, which here is heat cooling water takes anyway. Correct credit: 0. (No effect on the published
    outputs: the spray-dryer case sets no chiller COP.)"""
    c = load_case(ROOT / "cases" / "spray_dryer.json")
    s = with_extra_shift(load_streams(c.stream_file), c.extra_shift_K)
    d = design_from_gcc(s, c.sink_levels, c.eta_lorenz, c.source_T_C)
    cooling = CoolingCascade.from_table(problem_table(s), c.ambient_T_C)
    assert cooling.refrigeration > 0
    assert d.integration.Q_cold_utility_replaced > 0                      # what the old model credited
    assert refrigeration_taken_over(d.units, cooling) == pytest.approx(0.0, abs=1e-9)
