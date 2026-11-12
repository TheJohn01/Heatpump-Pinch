"""COP from manufacturer data (pinch.cop_data): the published fits reproduced, the design hook, sensitivity rows."""

import math

import pandas as pd
import pytest

from pinch import cop_data as cd
from pinch.case import load_case
from pinch.design import design_from_gcc
from pinch.sensitivity import apply, parse_sensitivities
from pinch.streams import load_streams, with_extra_shift
from pinch.validation import ROOT


@pytest.fixture(scope="module")
def brewery():
    case = load_case(ROOT / "cases" / "brewery.json")
    return case, with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)


def test_sghp_fit_reproduces_the_published_table():
    """Arpagaus (2026), Fig. 2: COP at 40, 50, ..., 100 K lift = 3.8, 3.2, 2.8, 2.5, 2.3, 2.1, 2.0 (rounded)."""
    fit = cd.FITS["arpagaus2026_sghp"]
    for lift, cop in zip(range(40, 101, 10), (3.8, 3.2, 2.8, 2.5, 2.3, 2.1, 2.0)):
        assert fit.cop(lift, 120) == pytest.approx(cop, abs=0.05)


def test_jesper_recommended_and_exponential_fits_agree():
    """Jesper et al. (2021), Table 6: Eq. 4-6.2 (used) and Eq. 4-7 (COP = 10.204 exp(-0.023347 lift)) have the same
    σ = 0.28 and R² = 0.96, so the transcribed coefficients must give nearly the same COP (Fig. 17)."""
    fit = cd.FITS["jesper2021_hthp"]
    for lift in range(20, 75, 5):
        assert fit.cop(lift, 60) == pytest.approx(10.204 * math.exp(-0.023347 * lift), abs=0.2)


@pytest.mark.parametrize("key, eta2nd, sigma, points", [
    ("jesper2021_vhthp", 0.42659, 0.22, [(40, 110), (60, 130), (80, 150)]),   # Table 7, Eq. 4-3
    ("jesper2021_r717", 0.54375, 0.41, [(40, 75), (55, 80), (70, 85)]),       # Table 8, Eq. 4-3
])
def test_fits_with_sink_temperature_use_kelvin(key, eta2nd, sigma, points):
    """The recommended fits agree with each paper's own constant-η2nd fit (COP = η2nd T_sink,out / lift, T in K)
    within 2σ of that fit; with T in °C they would be about a third lower, so this pins the unit."""
    fit = cd.FITS[key]
    for lift, T in points:
        assert fit.cop(lift, T) == pytest.approx(eta2nd * (T + 273.15) / lift, abs=2 * sigma)


def test_fit_choice_and_range():
    assert cd.default_fit(82).key == "jesper2021_hthp"
    assert cd.default_fit(103).key == "jesper2021_vhthp"
    fit = cd.FITS["jesper2021_hthp"]
    assert fit.in_range(50, 80, 30) and not fit.in_range(83, 82, -1)


def test_second_law_and_cop_floor():
    with pytest.raises(ValueError, match="not above 1"):
        cd.vendor_cop(cd.UnitPoint("huge lift", 300, 300, -50, -50))
    p = cd.UnitPoint("glide", 40, 80, 30, 30)                  # fit 3.19, reversible 11.2 (50 K lift)
    assert cd.vendor_cop(p) < p.cop_lorenz(1.0)
    with pytest.raises(ValueError, match="second law"):
        cd.vendor_cop(p, glide_gain=3.0)


def test_glide_gain_only_for_large_sink_glides():
    small = cd.UnitPoint("small", 75, 80, 30, 30)
    large = cd.UnitPoint("large", 40, 80, 30, 30)
    base = cd.FITS["jesper2021_hthp"].cop(50, 80)
    assert cd.vendor_cop(small, glide_gain=0.16) == pytest.approx(base)
    assert cd.vendor_cop(large, glide_gain=0.16) == pytest.approx(base * 1.16)


def test_brewery_points_and_ranges(brewery):
    """Design temperatures of the brewery (T*, source -1 °C) and the fit COPs (pinned)."""
    case, streams = brewery
    r = cd.cop_ranges(case, streams, cd.demonstration_eta_range()).set_index("unit")
    hp1, hp2 = r.loc["Warm-water HP"], r.loc["HTHP (wort boiling)"]
    assert (hp1.lift_K, hp2.lift_K) == (83.0, 104.0)
    assert hp1.COP_basis == pytest.approx(3.225, abs=1e-3) and hp2.COP_basis == pytest.approx(1.808, abs=1e-3)
    assert hp1.COP_fit == pytest.approx(1.631, abs=1e-3) and hp2.COP_fit == pytest.approx(1.709, abs=1e-3)
    assert not hp1.fit_in_range and not hp2.fit_in_range          # 83 > 78 K and 104 > 95 K: extrapolated
    assert hp1.COP_glide_blend == pytest.approx(1.631 * 1.16, abs=2e-3) and math.isnan(hp2.COP_glide_blend)
    assert hp2.COP_sghp_fit == pytest.approx(52.94 * 104 ** -0.716, abs=1e-3)
    assert hp1.COP_demo_eta_min <= hp1.COP_demo_eta_median <= hp1.COP_demo_eta_max


def test_apply_vendor_gives_the_fit_cop_in_the_design(brewery):
    case, streams = brewery
    for sigma in (-1, 0, 1):
        c = cd.apply_vendor(case, streams, sigma)
        d = design_from_gcc(streams, c.sink_levels, c.eta_lorenz, c.source_T_C)
        for p, u in zip(cd.level_points(case, streams), sorted(d.units, key=lambda u: u.T_sink_out_C)):
            assert u.COP == pytest.approx(cd.vendor_cop(p, sigma), rel=1e-9)


def test_sensitivity_kind(brewery):
    case, streams = brewery
    rows = parse_sensitivities([{"label": "a", "kind": "vendor_cop", "value": -1},
                                {"label": "b", "kind": "vendor_cop", "value": {"sigma": 0, "glide_gain": 0.16}}])
    assert rows[0].value == {"sigma": -1.0, "glide_gain": 0.0}
    with pytest.raises(ValueError):
        parse_sensitivities([{"label": "c", "kind": "vendor_cop", "value": {"lift": 3}}])
    with pytest.raises(ValueError, match="stream set"):
        apply(case, "vendor_cop", rows[0].value)
    c = apply(case, "vendor_cop", rows[1].value, streams=streams)
    eta = {lv.name: lv.eta_lorenz for lv in c.sink_levels}
    assert eta["Warm-water HP"] == pytest.approx(1.631 * 1.16 / 6.45, abs=0.01)   # glide 64 K: gain applied


def test_fits_against_demonstration_plants():
    """Every closed-cycle demonstration plant of IEA HPT Annex 58 reaches or beats the fit (pinned)."""
    d = pd.read_csv(cd.DEMO_FILE, comment="#")
    chk = cd.check_against_demonstrations(d)
    assert len(chk) == 5 and (chk["deviation"] >= 0).all()
    assert chk.set_index("no").loc[2, "deviation"] == pytest.approx(0.548, abs=1e-3)   # CO2, 100 K sink glide


def test_demonstration_eta_range():
    lo, med, hi = cd.demonstration_eta_range()
    assert (round(lo, 3), round(med, 3), round(hi, 3)) == (0.346, 0.37, 0.545)
