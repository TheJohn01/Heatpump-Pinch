"""Tests for the heat pump module (workflow step 4).

1. COP model: hand-calculated values, then the paper's published COPs.
2. Laws: first-law balance per unit, second-law limit on COP.
3. Placement rules on the four-stream example (pinch at T* = 145 °C):
   across pinch  -> Qh falls by Q_sink, Qc falls by Q_source;
   above pinch   -> Qh falls by W only, Qc unchanged;
   below pinch   -> Qh unchanged, Qc rises by W.
4. GCC sizing against an analytic answer.
"""

import math

import pytest

from pinch import load_streams, problem_table
from pinch.heat_pump import (
    HeatPump,
    add_units,
    classify_placement,
    integrate,
    lorenz_cop,
    max_useful_sink_duty,
    thermodynamic_mean_temperature_K,
)
from pinch.validation import ROOT

FOURSTREAM = load_streams(ROOT / "data" / "fourstream_example.csv")
BREWERY = load_streams(ROOT / "data" / "brewery_streams.csv")


# --------------------------------------------------------------- COP model
def test_mean_temperature_isothermal():
    assert thermodynamic_mean_temperature_K(100, 100) == pytest.approx(373.15)


def test_mean_temperature_glide():
    expected = 64 / math.log(355.15 / 291.15)
    assert thermodynamic_mean_temperature_K(18, 82) == pytest.approx(expected)


def test_lorenz_isothermal_equals_scaled_carnot():
    carnot = 376.15 / (376.15 - 272.15)
    assert lorenz_cop(103, 103, -1, -1, 0.55) == pytest.approx(0.55 * carnot)


def test_paper_cop_co2_heat_pump():
    """Padullés et al. (2026) Sec. 4.3.2: COP 3.5 (Fig. 14 implies 8.3 / 2.4 = 3.46)."""
    assert lorenz_cop(18, 82, -1, -1, 0.55) == pytest.approx(3.5, abs=0.1)


def test_paper_cop_hthp():
    """Padullés et al. (2026) Sec. 4.3.2: HTHP COP 2."""
    assert lorenz_cop(103, 103, -1, -1, 0.55) == pytest.approx(2.0, abs=0.05)


# ---------------------------------------------------------------------- laws
def test_first_law_per_unit():
    hp = HeatPump("HP", 10.0, 18, 82, -1, -1, eta_lorenz=0.55)
    assert hp.Q_source + hp.W == pytest.approx(hp.Q_sink)


def test_second_law_rejects_cop_above_reversible():
    with pytest.raises(ValueError, match="second law"):
        HeatPump("bad", 1.0, 110, 110, 100, 100, cop_fixed=50.0)  # reversible COP is 38.3


def test_second_law_rejects_eta_above_one():
    with pytest.raises(ValueError):
        lorenz_cop(103, 103, -1, -1, 1.2)


def test_electric_heater_has_no_source():
    eb = HeatPump("EB", 1.4, 87, 98, cop_fixed=1.0)
    assert eb.W == pytest.approx(1.4) and eb.Q_source == 0.0


# --------------------------------------------------------- placement rules
def _targets_with(unit):
    """Qh and Qc with the whole source duty taken from the process."""
    extended = add_units(FOURSTREAM, [unit], {unit.name: unit.Q_source})
    t = problem_table(extended)
    return t.Qh_min, t.Qc_min


BASE = problem_table(FOURSTREAM)  # Qh 7.5 MW, Qc 10.0 MW, pinch T* 145 °C


def test_across_pinch_saves_both_utilities():
    hp = HeatPump("HP", 1.0, 200, 200, 100, 100, eta_lorenz=0.5)
    Qh, Qc = _targets_with(hp)
    assert classify_placement(hp, 145) == "across pinch"
    assert Qh == pytest.approx(BASE.Qh_min - hp.Q_sink)
    assert Qc == pytest.approx(BASE.Qc_min - hp.Q_source)


def test_above_pinch_only_replaces_utility_with_work():
    hp = HeatPump("HP", 1.0, 240, 240, 200, 200, eta_lorenz=0.5)
    Qh, Qc = _targets_with(hp)
    assert classify_placement(hp, 145) == "above pinch"
    assert Qh == pytest.approx(BASE.Qh_min - hp.W)
    assert Qc == pytest.approx(BASE.Qc_min)


def test_below_pinch_turns_work_into_waste_heat():
    hp = HeatPump("HP", 1.0, 120, 120, 50, 50, eta_lorenz=0.5)
    Qh, Qc = _targets_with(hp)
    assert classify_placement(hp, 145) == "below pinch"
    assert Qh == pytest.approx(BASE.Qh_min)
    assert Qc == pytest.approx(BASE.Qc_min + hp.W)


def test_integrate_across_pinch_takes_source_from_process():
    hp = HeatPump("HP", 1.0, 200, 200, 100, 100, eta_lorenz=0.5)
    r = integrate(FOURSTREAM, [hp])
    assert r.Q_sink_useful == pytest.approx(1.0)
    assert r.Q_source_process["HP"] == pytest.approx(hp.Q_source)
    assert r.Q_source_external["HP"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------- GCC sizing
def test_max_useful_sink_duty_matches_gcc():
    """Sink in [189, 190] °C: limited by the GCC minimum above it, 3.0 MW at T* = 195 °C."""
    hp = HeatPump("HP", 1.0, 190, 190, 100, 100, eta_lorenz=0.5)
    assert max_useful_sink_duty(FOURSTREAM, hp) == pytest.approx(3.0, abs=1e-6)


def test_max_useful_sink_duty_above_gcc_top_is_full_qh():
    hp = HeatPump("HP", 1.0, 103, 103, -1, -1, eta_lorenz=0.55)
    assert max_useful_sink_duty(BREWERY, hp) == pytest.approx(problem_table(BREWERY).Qh_min, abs=1e-6)
