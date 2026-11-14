"""Tests for network synthesis and evaluation (``pinch.hen_design``) and pressure-drop based film
coefficients (``pinch.pressure_drop``).

Known answers: the four-stream problem of Sagli et al. (1990) as published by Polley and Panjeh Shahi (1991)
(targets, Networks 6.1 and 5.1: exchanger sizes and capital costs), the Euler minimum number of units,
hand calculations, and the derivation of the pressure-drop relation from tube geometry.
"""

import json
import math
from dataclasses import replace

import pandas as pd
import pytest

from pinch import load_streams, problem_table
from pinch.area import area_target
from pinch.hen_design import (
    CostLaw,
    Exchanger,
    MatchLoad,
    UtilityStream,
    break_loops,
    evaluate_exchangers,
    find_loop,
    min_units_matches,
    overall_U,
    pinch_design,
    series_network,
)
from pinch.pressure_drop import (
    SHELL_EXPONENT,
    TUBE_EXPONENT,
    Fluid,
    coefficients_from_pressure_drop,
    shell_side_K,
    tube_side_K,
)

SAGLI = "data/sagli1990_four_stream.csv"
DATA = json.load(open("data/benchmarks/sagli1990_networks.json", encoding="utf-8"))


def _ends(s):
    e = {x.name: (x.T_in_C, x.T_out_C, x.kind) for x in s.streams}
    e.update({k: tuple(v) for k, v in DATA["utilities"].items()})
    return e


def _shifted(s, emat):
    return replace(s, streams=tuple(replace(x, dT_shift_K=emat / 2) for x in s.streams))


# ---------------------------------------------------------------- evaluation
def test_lmtd_and_U_hand_calculation():
    """E1 of Network 6.1: H1 150 -> 60 against C1 37.5 -> 109.5, 1800 kW, h = 0.1 kW/m²K on both sides:
    LMTD = (40.5 - 22.5) / ln(40.5/22.5) = 30.62 K, U = 0.05, A = 1175.6 m² (Table 4)."""
    e = Exchanger("H1", "C1", 1800.0, 150.0, 60.0, 37.5, 109.5)
    assert e.lmtd_K == pytest.approx(18 / math.log(40.5 / 22.5))
    assert overall_U(0.1, 0.1) == pytest.approx(0.05)
    assert evaluate_exchangers((e,), {"H1": 0.1, "C1": 0.1})["area_m2"] == pytest.approx(1175.6, abs=0.1)
    with pytest.raises(ValueError, match="cross"):
        _ = Exchanger("H", "C", 1.0, 100.0, 50.0, 60.0, 110.0).lmtd_K


@pytest.mark.parametrize("name", ["6.1", "5.1"])
def test_published_networks_sizes_and_cost(name):
    """Sizes within 0.2 % of Tables 4-5 (figure temperatures are rounded to 0.1 °C) and capital cost within
    0.01 % of Fig. 1 (k$ 716.0 / 717.3)."""
    s = load_streams(SAGLI)
    nd = DATA["networks"][name]
    net = series_network(tuple(MatchLoad(a, b, q) for a, b, q in nd["matches"]), _ends(s))
    ev = evaluate_exchangers(net.exchangers, {k: 0.1 for k in _ends(s)}, CostLaw(**DATA["cost_law"]))
    for x in ev["exchangers"]:
        assert x["area_m2"] == pytest.approx(nd["published_expected_area_m2"][f"{x['hot']}-{x['cold']}"], rel=2e-3)
    assert ev["cost"] == pytest.approx(nd["published_capital_cost"], rel=1e-4)


def test_series_network_recovers_network_5_1_temperatures():
    """Fig. 3: C2 heated 25 -> 40 by H2 and 40 -> 100 by H1; H2 90 -> 70.6 on C1 (20 -> 82), then C2."""
    s = load_streams(SAGLI)
    nd = DATA["networks"]["5.1"]
    net = series_network(tuple(MatchLoad(a, b, q) for a, b, q in nd["matches"]), _ends(s))
    t = {(e.hot, e.cold): e for e in net.exchangers}
    assert t["H1", "C2"].T_cold_in_C == pytest.approx(40.0)
    assert t["H2", "C1"].T_cold_out_C == pytest.approx(82.0)
    assert t["H2", "C1"].T_hot_out_C == pytest.approx(70.625)
    assert net.min_approach_K == pytest.approx(8.0)


# ---------------------------------------------------------------- synthesis
def test_targets_of_the_four_stream_problem():
    t = problem_table(load_streams(SAGLI))
    assert (t.Qh_min, t.Qc_min) == pytest.approx((1075.0, 400.0))


def test_minimum_units_reaches_euler_bound_at_the_published_approach():
    """At an 8 K exchanger approach (Network 5.1's smallest) 5 units suffice: N - 1 with N = 4 streams + 2
    utilities; the network is feasible in series and keeps Q̇h = 1075 kW."""
    s = _shifted(load_streams(SAGLI), 8.0)
    r = min_units_matches(s, [UtilityStream("ST", "hot", 180, 180, 4.0)], [UtilityStream("CW", "cold", 10, 15, 4.0)],
                          Qh=1075.0)
    assert r.units == r.euler_minimum == 5
    assert r.hot_utility["ST"] == pytest.approx(1075.0) and r.cold_utility["CW"] == pytest.approx(400.0)
    net = series_network(r.matches, _ends(s), {(m.hot, m.cold): 8.0 for m in r.matches})
    assert not net.violations


def test_strict_approach_needs_a_sixth_unit():
    """With every exchanger at >= 20 K, 5 units cannot reach Q̇h,min (the programme proves 6 is minimal)."""
    s = load_streams(SAGLI)
    r = min_units_matches(s, [UtilityStream("ST", "hot", 180, 180, 10.0)], [UtilityStream("CW", "cold", 10, 15, 10.0)])
    assert r.units == 6 and r.euler_minimum == 5
    loads = {}
    for m in r.matches:                               # every stream's load is matched exactly
        loads[m.hot] = loads.get(m.hot, 0.0) + m.Q
        loads[m.cold] = loads.get(m.cold, 0.0) + m.Q
    for x in s.streams:
        assert loads[x.name] == pytest.approx(x.Q)


def test_synthesis_rejects_a_hot_utility_below_the_target():
    s = load_streams(SAGLI)
    with pytest.raises(ValueError, match="below the energy target"):
        min_units_matches(s, [UtilityStream("ST", "hot", 180, 180, 10.0)], [UtilityStream("CW", "cold", 10, 15, 10.0)],
                          Qh=1000.0)


def test_more_hot_utility_than_needed_is_allowed():
    s = load_streams(SAGLI)
    r = min_units_matches(s, [UtilityStream("ST", "hot", 180, 180, 10.0)], [UtilityStream("CW", "cold", 10, 15, 10.0)],
                          Qh=1200.0)
    assert r.cold_utility["CW"] == pytest.approx(525.0)


# ---------------------------------------------------------------- pressure drop
def test_tube_side_relation_from_geometry():
    """Independent calculation: N tubes of bore d and length l, velocity u = 4V/(N π d²); Dittus-Boelter h,
    Fanning ΔP = 2 f (l/d) ρ u² with f = 0.046 Re^-0.2, A = N π d l. Must equal K A h^3.5."""
    f = Fluid(rho=800, mu=5e-4, k=0.12, cp=2600)
    d, V, N, l = 0.0154, 0.0096, 60, 4.0
    u = 4 * V / (N * math.pi * d ** 2)
    Re = f.rho * u * d / f.mu
    h = 0.023 * Re ** 0.8 * f.Pr ** (1 / 3) * f.k / d
    dP = 2 * 0.046 * Re ** -0.2 * (l / d) * f.rho * u ** 2
    A = N * math.pi * d * l
    assert dP == pytest.approx(tube_side_K(f, d, V) * A * h ** TUBE_EXPONENT, rel=1e-10)


def test_shell_side_exponent():
    """2.81 / 0.55 = 5.109 (Polley et al. 1990, Eq. A2.13, printed 5.1); K positive and finite."""
    assert SHELL_EXPONENT == pytest.approx(5.109, abs=1e-3)
    assert 0 < shell_side_K(Fluid(800, 5e-4, 0.12, 2600), 0.024, 0.0191, 0.0254, 0.01) < math.inf


def test_fixed_point_returns_known_coefficients():
    """K chosen so that h = 800 W/m²K spends exactly the usable pressure drop: the algorithm returns 800,
    and its area equals the Bath area target at 0.8 kW/m²K."""
    s = load_streams(SAGLI)
    h0, n = 800.0, {x.name: TUBE_EXPONENT for x in s.streams}
    A = area_target(s, {x.name: h0 / 1000 for x in s.streams}).contributions
    kind = {x.name: x.kind for x in s.streams}
    CP = {x.name: x.CP for x in s.streams}
    contact = {}
    for j in A:
        opp = [k for k in A if kind[k] != kind[j]]
        contact[j] = A[j] + sum(CP[k] / sum(CP[o] for o in opp) * A[k] for k in opp)
    dP = {j: 1e4 for j in A}
    K = {j: 0.9 * dP[j] / (contact[j] * h0 ** TUBE_EXPONENT) for j in A}
    r = coefficients_from_pressure_drop(s, dP, K, n)
    assert all(v == pytest.approx(h0, rel=1e-6) for v in r.h.values())
    assert r.area_m2 == pytest.approx(area_target(s, {k: h0 / 1000 for k in A}).area, rel=1e-6)


def test_benchmark_hen_reproduces_the_published_values():
    from scripts.benchmarks import benchmark_hen
    df = benchmark_hen.run()
    exact = df[df["source"].str.startswith(("Table 1", "Table 12", "Tables 4-5, expected", "Fig. 1"))]
    assert len(exact) == 16                                   # 3 targets, 11 exchanger sizes, 2 costs
    assert (exact["deviation_pct"].abs() <= 0.2).all()
    pd_rows = df[df["check"].str.contains("pressure-drop basis \\[m²\\]")]
    assert (pd_rows["deviation_pct"].abs() < 30).all()        # within 30 % of the detailed designs
    assumed = df[df["check"].str.contains("assumed h")]
    assert (assumed["deviation_pct"] > 500).all()             # the assumed coefficient overpredicts sevenfold


# ---------------------------------------------------------------- independent tool
def test_openpinch_benchmark_matches_to_six_decimals():
    """Every case against OpenPinch 0.8.3 (stored results): Q̇h,min and Q̇c,min within 1e-6 relative, pinch equal."""
    from scripts.benchmarks import benchmark_openpinch
    df = benchmark_openpinch.compare()
    assert len(df) == 11
    assert (df["max_rel_deviation"] <= 1e-6).all()
    both = df.dropna(subset=["pinch_T_star_ours", "pinch_T_star_OpenPinch"])
    assert (both["pinch_T_star_ours"] - both["pinch_T_star_OpenPinch"]).abs().max() < 1e-6


def test_openpinch_conversion_round_trip():
    """Our stream set -> OpenPinch input -> back gives the same streams (temperatures, loads, shifts)."""
    from pinch.streams import streams_from_frame
    from scripts.benchmarks import benchmark_openpinch as b
    s = load_streams("data/brewery_streams.csv")
    back = streams_from_frame(b.from_openpinch(b.to_openpinch(s)))
    assert [(x.T_in_C, x.T_out_C, x.Q, x.dT_shift_K) for x in back.streams] == \
        pytest.approx([(x.T_in_C, x.T_out_C, x.Q, x.dT_shift_K) for x in s.streams])
    assert isinstance(b.from_openpinch(json.load(open(b.SAMPLES / "basic_pinch.json"))), pd.DataFrame)


def test_letsios2018_benchmark_subset():
    """Published minimum numbers of matches (Letsios et al. 2018, proven optimal except 28sp-as1)."""
    from scripts.benchmarks.benchmark_min_matches import run
    df = run(["4sp1", "6sp-gg1", "7sp-cm1", "8sp-fs1", "15sp-tkm", "28sp-as1"])
    assert df["agrees"].all(), df[["instance", "units_here", "units_published"]]


def test_letsios2018_committed_benchmark_agrees():
    df = pd.read_csv("outputs/benchmark_min_matches.csv")
    assert len(df) == 20 and df["agrees"].all()


# ---------------------------------------------------------------- Pinch Design Method
@pytest.mark.parametrize("path, Qh, Qc", [(SAGLI, 1075.0, 400.0),                     # Polley 1991, Table 1
                                          ("data/aromatics_plant_streams.csv", 21680.0, 29400.0),   # Table 12
                                          ("data/four_stream_process_streams.csv", 7.5, 10.0)])     # Oklahoma Ex. 1.1
def test_pinch_design_meets_the_published_targets_with_fewest_units(path, Qh, Qc):
    """The MER network keeps the published energy targets, nothing crosses the pinch, every match keeps the
    stream shifts, and the unit count is (N - 1) above plus (N - 1) below the pinch."""
    from pinch.network import evaluate_network
    s = load_streams(path)
    d = pinch_design(s, "ST", "CW")
    r = evaluate_network(s, d.to_network("MER"))
    assert (r.Qh, r.Qc) == pytest.approx((Qh, Qc))
    assert r.cross_pinch_matches + r.heaters_below_pinch + r.coolers_above_pinch == pytest.approx(0.0, abs=1e-6)
    assert r.matches["feasible"].all()
    assert d.units == d.units_target


def test_four_stream_mer_design_splits_H2_below_the_pinch():
    """Below the pinch (T* 80 °C) both cold streams need a pinch partner with CP >= theirs; only H2 (80 kW/K)
    has one, so H2 is split (CP rule); above it H1 (20) goes to C1 (25). 3 + 4 = 7 units."""
    d = pinch_design(load_streams(SAGLI), "ST", "CW")
    assert d.pinch_T_star_C == 80.0 and d.units_target == 7 and d.splits == 1
    branches = [m for m in d.matches if m.hot == "H2"]
    assert {m.cold for m in branches} == {"C1", "C2"} and sum(m.hot_seg[2] for m in branches) == pytest.approx(1.0)
    for m in branches:                                  # each branch obeys the CP rule
        assert 80.0 * m.hot_seg[2] >= {"C1": 25.0, "C2": 30.0}[m.cold] - 1e-9


def test_designed_network_round_trips_through_the_network_file(tmp_path):
    from pinch.network import evaluate_network, load_networks, network_to_json
    s = load_streams(SAGLI)
    net = pinch_design(s).to_network("MER")
    f = tmp_path / "n.json"
    f.write_text(json.dumps({"networks": {"MER": network_to_json(net)}}), encoding="utf-8")
    back = load_networks(f)["MER"]
    assert [m.name for m in back.matches] == [m.name for m in net.matches]
    assert evaluate_network(s, back).Qh == pytest.approx(1075.0)


def test_split_branches_must_cover_their_range():
    from pinch.network import Match, Network, Segment, evaluate_network
    s = load_streams(SAGLI)
    half = Network("x", (Match("a", (Segment("H2", 90, 60, 0.5),), (Segment("C2", 25, 65),)),))
    with pytest.raises(ValueError, match="split branches cover"):
        evaluate_network(s, half)


def test_find_loop_and_euler_count():
    """Two units on one pair form a loop; a tree (N - 1 units) has none."""
    assert find_loop((MatchLoad("H", "C", 5.0), MatchLoad("H", "C", 2.0))) == [1, 0]
    assert find_loop((MatchLoad("H", "C", 5.0), MatchLoad("H", "CW", 2.0), MatchLoad("ST", "C", 1.0))) is None


def test_loop_breaking_reaches_the_euler_minimum_of_network_5_1():
    """Breaking the two loops of the MER network at constant energy leaves 5 units (= N - 1 with the two
    utilities) at Q̇h 1075 kW, like Network 5.1 (Polley and Panjeh Shahi 1991, Fig. 3); every stream keeps
    its duty. Restoring a 12 K approach costs extra hot utility along a utility path."""
    s = load_streams(SAGLI)
    d = pinch_design(s, "ST", "CW")
    ends = _ends(s)
    req = {(a, b): 12.0 for a in "H1 H2".split() for b in "C1 C2".split()}
    lb = break_loops(d.unit_loads(), ends, req, {"ST"}, {"CW"}, relax=False)
    assert len(lb.units) == len(DATA["networks"]["5.1"]["matches"]) == 5
    assert lb.hot_utility == pytest.approx(1075.0)
    for x in s.streams:
        assert sum(u.Q for u in lb.units if x.name in (u.hot, u.cold)) == pytest.approx(x.Q)
    relaxed = break_loops(d.unit_loads(), ends, req, {"ST"}, {"CW"})
    assert relaxed.hot_utility > 1075.0 + 1.0 and not relaxed.network.violations
    assert relaxed.network.min_approach_K >= 12.0 - 1e-4
    assert any(st["relaxed_by"] > 0 for st in relaxed.steps)


def test_benchmark_pinch_design_reproduces_the_published_values():
    from scripts.benchmarks import benchmark_pinch_design
    df, nets = benchmark_pinch_design.run()
    pub = df[df["source"].str.startswith(("Table 1", "Oklahoma", "Network 5.1 (Fig. 3)"))
             & ~df["source"].str.contains("comparison") & df["published"].notna()]
    assert len(pub) == 8 and (pub["deviation_pct"].abs() < 1e-6).all()   # 6 targets, 5.1 units and Q̇h
    assert (df.loc[df["check"].str.contains("across the pinch"), "reproduced"].abs() < 1e-6).all()
    units = df[df["check"] == "MER network units"]
    assert (units["reproduced"] == units["source"].str.extract(r": (\d+)$")[0].astype(float)).all()
    assert len(nets) == 5
