"""Tests for area and units targeting and supertargeting (workflow step 3).

1. Published interval areas: University of Oklahoma 'Units and Area Targeting'
   notes, four-stream example with utilities, U = 0.001 MW/(m2 K): six intervals,
   published total 2716.3 m2. Intervals I-V reproduced; interval VI contains an
   arithmetic error; the corrected total (2757.3 m2) equals our composite area.
2. Analytic checks of the Bath formula on composite curves.
3. Units target, uniform ΔTmin and supertargeting behaviour.
"""

import math

import pytest

from pinch import load_streams
from pinch.area import CostLaw, area_target, log_mean, supertarget, units_target, with_uniform_dTmin
from pinch.streams import Stream, StreamSet
from pinch.validation import ROOT

# (Q [MW], TH1, TH2, TC1, TC2, published ΔT_LM, published A [m2]) — the notes' table
OU_INTERVALS = [
    (6, 80, 40, 15, 20, 40.0, 150.1),
    (4, 90, 80, 20, 30, 60.0, 66.7),
    (24, 150, 90, 20, 140, 30.8, 778.4),
    (20, 200, 150, 140, 180, 14.4, 1386.3),
    (7.5, 250, 200, 180, 205, 30.8, 243.3),
    (7.5, 300, 250, 205, 230, 81.9, 91.6),
]


def test_published_interval_areas():
    """Intervals I-V reproduce exactly. Interval VI's published ΔT_LM (81.9 K) uses the cold
    temperatures of interval V (180 -> 205 °C); with its own printed temperatures (205 -> 230 °C)
    ΔT_LM is 56.6 K. The corrected total equals our composite-curve area (next test)."""
    U = 0.001  # MW/(m2 K)
    for Q, th1, th2, tc1, tc2, dtlm_pub, a_pub in OU_INTERVALS[:5]:
        dtlm = log_mean(th1 - tc2, th2 - tc1)
        assert dtlm == pytest.approx(dtlm_pub, abs=0.05)
        assert Q / (U * dtlm) == pytest.approx(a_pub, abs=0.1)
    assert log_mean(300 - 205, 250 - 180) == pytest.approx(81.9, abs=0.05)   # the published error
    assert log_mean(300 - 230, 250 - 205) == pytest.approx(56.58, abs=0.01)  # correct temperatures


def test_composite_area_equals_corrected_published_total():
    published_I_to_V = sum(a for *_, a in OU_INTERVALS[:5])        # 2624.8 m2
    corrected_total = published_I_to_V + 7.5 / (0.001 * log_mean(300 - 230, 250 - 205))
    s = load_streams(ROOT / "data" / "fourstream_balanced_ou.csv")
    at = area_target(s, {x.name: 0.002 for x in s.streams}, include_utilities=True)
    assert at.area == pytest.approx(corrected_total, abs=0.5)      # rounding of published areas


def test_log_mean_limits():
    assert log_mean(10, 10) == pytest.approx(10)
    assert log_mean(20, 10) == pytest.approx(10 / math.log(2))
    with pytest.raises(ValueError):
        log_mean(5, -1)


def _two_streams(h_hot=1.0, h_cold=1.0):
    """Balanced counter-current pair: hot 150 -> 50, cold 40 -> 140, CP 1 kW/K, 100 kW."""
    s = StreamSet((Stream("H", "hot", 150, 50, 100.0, 5.0), Stream("C", "cold", 40, 140, 100.0, 5.0)), "kW")
    return s, {"H": h_hot, "C": h_cold}


def test_bath_formula_single_match_analytic():
    """Equal CPs: ΔT = 10 K everywhere, so A = Q (1/h_h + 1/h_c) / 10."""
    s, h = _two_streams(0.5, 2.0)
    at = area_target(s, h)
    assert at.heat_recovered == pytest.approx(100.0)
    assert at.area == pytest.approx(100.0 * (1 / 0.5 + 1 / 2.0) / 10.0)
    assert at.units == 1


def test_area_rises_as_dTmin_falls():
    s = load_streams(ROOT / "data" / "fourstream_example.csv")
    h = {x.name: 0.002 for x in s.streams}
    areas = [area_target(with_uniform_dTmin(s, d), h).area for d in (5, 10, 20, 30)]
    assert areas == sorted(areas, reverse=True)


def test_units_target_fourstream():
    """Four streams with a pinch: 4 streams above (3 units) and 3 below (2 units)."""
    s = load_streams(ROOT / "data" / "fourstream_example.csv")
    assert units_target(s) == 3 + 2


def test_units_target_balanced_problem():
    """With utilities the process pinch (T* 145 °C) remains: 5 streams above and 5 below -> 4 + 4."""
    s = load_streams(ROOT / "data" / "fourstream_balanced_ou.csv")
    assert units_target(s) == 4 + 4


def test_missing_film_coefficient_is_an_error():
    s, _ = _two_streams()
    with pytest.raises(ValueError, match="film coefficient"):
        area_target(s, {"H": 1.0})


def test_supertarget_trade_off():
    """Energy cost rises and capital falls with ΔTmin; TAC = annualised capital + energy."""
    s = load_streams(ROOT / "data" / "fourstream_example.csv")
    h = {x.name: 0.002 for x in s.streams}
    law = CostLaw(a=0.0, b=1000.0, c=1.0, source="test values")
    rows = supertarget(s, h, [5, 10, 20, 40], law, crf_per_year=0.1, hot_utility_cost=1e5, cold_utility_cost=1e4)
    energy = [r["energy_cost_EUR"] for r in rows]
    capital = [r["capital_EUR"] for r in rows]
    assert energy == sorted(energy) and capital == sorted(capital, reverse=True)
    for r in rows:
        assert r["TAC_EUR"] == pytest.approx(r["annualised_capital_EUR"] + r["energy_cost_EUR"])


def test_brewery_optimum_matches_marginal_analysis(tmp_path):
    """RQ2: near the optimum the area grows logarithmically, dA/dΔTmin ≈ -62 m2 / ΔTmin,
    and each kelvin of ΔTmin adds 13.82 kW of hot utility. Equating marginal capital and
    energy cost gives ΔTmin,opt ≈ 62 b CRF / (13.82 c_h), linear in the area cost b."""
    from analyse import analyse
    from pinch.case import load_case
    s = analyse(load_case(ROOT / "cases" / "brewery_padulles2026.json"), output_root=tmp_path)
    rq2 = sorted(s["area_targeting"]["RQ2"], key=lambda r: r["b"])
    opts = [r["dTmin_opt_K"] for r in rq2]
    assert opts == sorted(opts)                                   # dearer area -> larger ΔTmin
    assert not any(r["at_grid_edge"] for r in rq2)                # optimum resolved inside the grid
    c_h = s["area_targeting"]["hot_utility_cost_EUR_per_kW_year"]
    crf = s["area_targeting"]["crf_per_year"]
    for r in rq2:
        approx = 62.0 * r["b"] * crf / (13.82 * c_h)
        assert r["dTmin_opt_K"] == pytest.approx(approx, rel=0.25, abs=0.05)  # grid resolution
