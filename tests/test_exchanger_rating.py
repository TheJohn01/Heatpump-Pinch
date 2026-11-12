"""Shell-and-tube rating with ht (pinch.exchanger_rating): known answers first, then the published designs
of Polley and Panjeh Shahi (1991, Tables 4-5)."""

import math

import pandas as pd
import pytest

from pinch import load_streams
from pinch.exchanger_rating import (
    TubeBundle,
    lmtd_correction,
    rate_exchangers,
    shells_required,
    tube_side,
)
from pinch.hen_design import CostLaw, Exchanger, MatchLoad, evaluate_exchangers, series_network
from pinch.pressure_drop import Fluid


def _bowman_1_2(P: float, R: float) -> float:
    """Classical closed form for one shell pass, two (or 2n) tube passes (Bowman, Mueller and Nagle 1940)."""
    S = math.sqrt(R * R + 1)
    return (S / (R - 1)) * math.log((1 - P) / (1 - P * R)) / math.log(
        (2 - P * (R + 1 - S)) / (2 - P * (R + 1 + S)))


def _PR(e: Exchanger) -> tuple[float, float]:
    P = (e.T_cold_out_C - e.T_cold_in_C) / (e.T_hot_in_C - e.T_cold_in_C)
    R = (e.T_hot_in_C - e.T_hot_out_C) / (e.T_cold_out_C - e.T_cold_in_C)
    return P, R


E = Exchanger("H", "C", 100.0, 150.0, 90.0, 30.0, 100.0)


def test_one_shell_equals_the_closed_form():
    P, R = _PR(E)
    assert lmtd_correction(E, 1) == pytest.approx(_bowman_1_2(P, R), rel=1e-10)


def test_n_shells_equal_one_shell_at_the_per_shell_effectiveness():
    """N identical shells in series: F_N(P, R) = F_1(P_1, R) with P_1 from W = ((1 - PR)/(1 - P))^(1/N)."""
    P, R = _PR(E)
    for n in (2, 3, 4):
        W = ((1 - P * R) / (1 - P)) ** (1 / n)
        P1 = (1 - W) / (R - W)
        assert lmtd_correction(E, n) == pytest.approx(_bowman_1_2(P1, R), rel=1e-9)


def test_isothermal_side_and_cross():
    assert lmtd_correction(Exchanger("ST", "C", 50.0, 180.0, 180.0, 80.0, 120.0), 1) == 1.0
    cross = Exchanger("H", "C", 100.0, 150.0, 60.0, 40.0, 140.0)         # deep cross: 1 shell impossible
    assert math.isnan(lmtd_correction(cross, 1))
    n, F = shells_required(cross)
    assert n > 1 and F >= 0.8
    with pytest.raises(ValueError, match="stays below"):
        shells_required(cross, max_shells=1)


def test_rated_area_and_cost_never_below_counter_current():
    law = CostLaw(8600, 670, 0.83)
    h = {"H": 0.1, "C": 0.1}
    cc = evaluate_exchangers((E,), h, law)
    r = rate_exchangers((E,), h, law)[0]
    assert r.area_counter_current_m2 == pytest.approx(cc["area_m2"])
    assert r.area_m2 == pytest.approx(cc["area_m2"] / r.F) and r.area_m2 >= cc["area_m2"]
    assert r.cost == pytest.approx(r.shells * law.cost(r.area_m2 / r.shells))


def test_tube_side_colburn_is_polleys_relation():
    """The clean coefficient is the Colburn relation behind Polley's ΔP = K A h^3.5 (0.023 Re^0.8 Pr^1/3 k/d);
    a wall of infinite conductivity and no fouling leave h_io = h_i d_i / d_o."""
    f = Fluid(rho=800, mu=5e-4, k=0.12, cp=2600)
    b = TubeBundle(tubes=60, passes=2, d_i_m=0.0154, d_o_m=0.0191, length_m=4.0)
    t = tube_side(f, 10.0, b)
    assert t.h_i_W_m2K == pytest.approx(0.023 * t.Re ** 0.8 * f.Pr ** (1 / 3) * f.k / 0.0154, rel=1e-12)
    clean = tube_side(f, 10.0, TubeBundle(60, 2, 0.0154, 0.0191, 4.0, k_wall_W_mK=1e12))
    assert clean.h_io_W_m2K == pytest.approx(clean.h_i_W_m2K * 0.0154 / 0.0191, rel=1e-9)
    with pytest.raises(ValueError, match="turbulent"):
        tube_side(f, 0.1, b)


def test_shell_counts_of_the_published_designs():
    """All eleven exchangers of Networks 6.1 and 5.1 get the published number of shells at F >= 0.8."""
    import json
    nets = json.loads(open("data/benchmarks/sagli1990_networks.json", encoding="utf-8").read())
    designs = json.loads(open("data/benchmarks/polley1991_exchanger_designs.json", encoding="utf-8").read())
    s = load_streams("data/sagli1990_four_stream.csv")
    ends = {x.name: (x.T_in_C, x.T_out_C, x.kind) for x in s.streams}
    ends.update({k: tuple(v) for k, v in nets["utilities"].items()})
    count = 0
    for name, nd in nets["networks"].items():
        net = series_network(tuple(MatchLoad(a, b, q) for a, b, q in nd["matches"]), ends)
        for e in net.exchangers:
            assert shells_required(e)[0] == designs["networks"][name][f"{e.hot}-{e.cold}"]["shells"]
            count += 1
    assert count == 11


def test_committed_benchmark_within_tolerances():
    df = pd.read_csv("outputs/benchmark_exchanger_rating.csv")
    dev = df.set_index("check")["deviation_pct"].abs()
    assert (dev[dev.index.str.endswith("shells")] == 0).all()
    assert (dev[dev.index.str.contains("Colburn")] < 0.5).all()
    assert (dev[dev.index.str.contains("ΔP")] < 4.0).all()
    assert (dev[dev.index.str.contains("area from published U")] < 1.5).all()
