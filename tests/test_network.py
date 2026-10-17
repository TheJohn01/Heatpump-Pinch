"""Tests for existing-network evaluation and retrofit (workflow step 5).

Known answers: Padullés et al. (2026), Sec. 4.2 and Figs. 5-7 (existing
brewery network: hot utility 11.3 kWh/hl, recovery 2.4 + 7.7); Sec. 4.1
(indirect-transfer target with an extra 2 K shift: Q̇h 10.5); Fig. 14 (CO2 heat
pump 8.3 kWh/hl). General identity: energy gap = cross-pinch transfer in
matches + heaters below the pinch + coolers above the pinch.
"""

import json

import pytest

from pinch import load_streams, problem_table
from pinch.network import Match, Network, Segment, constrained_streams, evaluate_network, load_networks
from pinch.validation import ROOT

BREWERY = ROOT / "data" / "brewery_streams.csv"
NETWORKS = ROOT / "data" / "brewery_networks.json"


@pytest.fixture(scope="module")
def brewery():
    return load_streams(BREWERY), load_networks(NETWORKS)


def _identity(r):
    return r.cross_pinch_matches + r.heaters_below_pinch + r.coolers_above_pinch


# ------------------------------------------------------------------ published brewery network
def test_existing_network_reproduces_paper(brewery):
    streams, nets = brewery
    r = evaluate_network(streams, nets["N0 existing"], T_amb_C=15)
    assert r.Qh == pytest.approx(11.3, abs=1e-3)            # published, Sec. 4.3.2 and 7
    assert r.heat_recovered == pytest.approx(2.4 + 7.7, abs=1e-3)   # Figs. 5 and 6
    assert r.Qc == pytest.approx(4.7, abs=1e-3)             # 14.8 - 10.1
    assert r.energy_gap == pytest.approx(_identity(r), abs=1e-3)
    assert r.cross_pinch_matches == 0 and r.heaters_below_pinch == 0
    # the whole gap is cooling above the pinch: condensate 100 -> 19 °C and wort 23 -> 19 °C
    assert r.coolers_above_pinch == pytest.approx(0.9 * 81 / 85 + 0.1 * 4, abs=1e-3)


def test_condensate_retrofit_reaches_indirect_target(brewery):
    """Condensate into the tank: Q̇h equals the paper's indirect target (10.5; ours 10.48)."""
    streams, nets = brewery
    r = evaluate_network(streams, nets["N1 condensate into tank"], T_amb_C=15)
    target_indirect = problem_table(streams.__class__(
        streams=tuple(s.__class__(**{**s.__dict__, "dT_shift_K": s.dT_shift_K + 2}) for s in streams.streams),
        energy_unit=streams.energy_unit, source="")).Qh_min
    assert r.Qh == pytest.approx(target_indirect, abs=1e-3)
    assert r.Qh == pytest.approx(10.5, abs=0.05)
    assert r.energy_gap == pytest.approx(_identity(r), abs=1e-3)


@pytest.mark.parametrize("name", ["N0 existing", "N1 condensate into tank"])
def test_constrained_stream_set_has_network_utility(brewery, name):
    streams, nets = brewery
    r = evaluate_network(streams, nets[name])
    # 1e-4: the tank-side segment ends are stored to 4 decimals in the network file
    assert problem_table(constrained_streams(streams, nets[name])).Qh_min == pytest.approx(r.Qh, abs=1e-4)


def test_paper_config2_heat_pump_duty(tmp_path):
    """Heat pumps on the existing network: warm-water HP 8.3 kWh/hl as in Fig. 14."""
    from analyse import compute
    from pinch.case import load_case
    s = compute(load_case(ROOT / "cases" / "brewery_padulles2026.json")).summary["retrofit"]
    row = next(o for o in s["options"] if o["network"] == "N0 existing")
    assert "Warm-water HP 8.30" in row["heat_pumps"]
    assert row["Qh_residual"] == pytest.approx(0.0, abs=1e-6)


# ------------------------------------------------------------------ general behaviour
def test_cross_pinch_match_is_counted():
    """Four-stream example: a hot stream above the pinch heating a cold stream below it."""
    streams = load_streams(ROOT / "data" / "fourstream_example.csv")
    pinch = problem_table(streams).pinch_T_star_C[0]
    assert pinch == 145
    bad = Network("cross", (Match("X", (Segment("Reactor 1 product", 250, 190),),
                                  (Segment("Reactor 1 feed", 20, 65),)),))
    r = evaluate_network(streams, bad)
    assert r.cross_pinch_matches == pytest.approx(9.0, rel=1e-3)
    assert r.energy_gap == pytest.approx(_identity(r), abs=1e-6)
    good = Network("below", (Match("Y", (Segment("Reactor 1 product", 100, 40),),
                                   (Segment("Reactor 1 feed", 20, 65),)),))
    r2 = evaluate_network(streams, good)
    assert r2.cross_pinch_matches == 0
    assert r2.energy_gap == pytest.approx(_identity(r2), abs=1e-6)


def test_no_matches_gap_equals_hot_above_plus_cold_below():
    streams = load_streams(ROOT / "data" / "fourstream_example.csv")
    r = evaluate_network(streams, Network("none", ()))
    assert r.Qh == pytest.approx(sum(s.Q for s in streams.cold))
    assert r.energy_gap == pytest.approx(_identity(r), abs=1e-6)


def test_infeasible_and_unbalanced_matches_are_rejected():
    streams = load_streams(ROOT / "data" / "fourstream_example.csv")
    with pytest.raises(ValueError, match="infeasible"):     # 5 K approach < 10 K required
        evaluate_network(streams, Network("n", (Match("Z", (Segment("Reactor 1 product", 100, 40),),
                                                          (Segment("Reactor 1 feed", 50, 95),)),)))
    with pytest.raises(ValueError, match="differs"):
        evaluate_network(streams, Network("n", (Match("Z", (Segment("Reactor 1 product", 100, 40),),
                                                          (Segment("Reactor 1 feed", 20, 60),)),)))
    with pytest.raises(ValueError, match="direction"):
        evaluate_network(streams, Network("n", (Match("Z", (Segment("Reactor 1 product", 40, 100),),
                                                          (Segment("Reactor 1 feed", 20, 65),)),)))


# ---------------------------------------------------------------- retrofit bracket without a published network
def test_retrofit_bounds_spray_dryer_published_no_recovery():
    """Liang et al. (2022): no air-to-air recovery today. Energy gap = steam heating below the pinch."""
    from analyse import compute
    from pinch.case import load_case
    from pinch.validation import ROOT
    s = compute(load_case(ROOT / "cases" / "walmsley2024_spray_dryer.json")).summary["retrofit_bounds"]
    assert s["baseline_status"] == "published"
    b0 = s["no_heat_recovery"]
    assert b0["Qh"] == pytest.approx(6031.0)                       # sum of the cold streams, Table 1
    assert b0["Qh"] - s["Qh_min"] == pytest.approx(b0["heaters_below_pinch"], abs=0.5)
    rows = {r["option"]: r for r in s["options"]}
    assert rows["New heat recovery at target"]["Qh_after"] == pytest.approx(s["Qh_min"], rel=1e-6)
    assert rows["New heat recovery at target"]["capex_EUR"] == pytest.approx(s["new_heat_recovery_network"]["capex_EUR"], rel=1e-6)


def test_retrofit_bounds_lower_bound_equals_step6():
    """The 'already at target' row is the grass-roots comparison of step 6."""
    from dataclasses import replace
    from analyse import compute
    from pinch.case import load_case
    from pinch.validation import ROOT
    c = load_case(ROOT / "cases" / "walmsley2024_milk_evaporator.json")
    s = compute(replace(c, basis={"type": "power", "operating_hours_per_year": 8000.0})).summary
    low = next(r for r in s["retrofit_bounds"]["options"] if r["option"].startswith("Lower bound"))
    full = s["economics"]["results"]["full design (heat recovery installed)"]
    assert low["capex_EUR"] == pytest.approx(full["capex_EUR"], rel=1e-6)
    assert low["npv_EUR"] == pytest.approx(full["npv_EUR"], rel=1e-4)
    assert s["retrofit_bounds"]["baseline_status"] == "likely_at_target"
