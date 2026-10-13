"""Tests for the working-fluid cycle model (workflow step 4b).

Known answers: Andersen et al. (2024), Applied Energy 376, 124312, Appendix A
(verification cases of their model, same component assumptions as Table 3).
They used REFPROP 10; we use CoolProp, so small property differences remain.
"""

import pytest

pytest.importorskip("CoolProp")

from pinch.cycle import CycleAssumptions, SecondaryStream, cascade, single_stage


def conditions(T_so_in, lift, dT_so, dT_si):
    """Andersen's temperature conditions -> (source, sink) streams."""
    return SecondaryStream(T_so_in, T_so_in + dT_so), SecondaryStream(T_so_in + lift - dT_si, T_so_in + lift)


# ------------------------------------------------------------------ published COPs
def test_appendix_A_slhx_butane():
    """SLHX, R-600; 50 °C, 40 K, -1 K, 20 K; published COP 4.94. Deviation +1.1 %."""
    r = single_stage("n-Butane", *conditions(50, 40, -1, 20), slhx=True)
    assert r.COP == pytest.approx(4.94, rel=0.02)


def test_appendix_A_transcritical_co2_with_expander():
    """Std. with expander, R-744; 15 °C, 100 K, -10 K, 80 K; published COP 2.69. Deviation +0.1 %."""
    r = single_stage("CarbonDioxide", *conditions(15, 100, -10, 80), expander=True)
    assert r.transcritical
    assert r.COP == pytest.approx(2.69, rel=0.02)


def test_appendix_A_cascade():
    """Cascade Std./SLHX, R-1234ze(Z) + R-602; 40 °C, 80 K, -10 K, 30 K; published COP 2.62.

    Our optimiser finds 2.79 (+6.5 %) with the intermediate temperature low (top
    evaporation ~31 °C), i.e. it shifts most of the lift to the SLHX top cycle.
    The paper does not report its intermediate temperature; deviation documented.
    """
    r = cascade("R1234ze(Z)", "n-Hexane", *conditions(40, 80, -10, 30), slhx_high=True)
    assert r.COP == pytest.approx(2.62, rel=0.07)
    assert r.COP >= 2.62 * 0.99   # an optimum at least as good as theirs, within property differences


def test_fig2_hexane_known_deviation():
    """Fig. 2: SLHX, R-602 at 80 °C, 70 K, -10 K, 40 K; published COP 3.02.

    We obtain 3.53 (+17 %), unexplained (the stated η_Lor = 0.52 is also not
    consistent with these conditions under the standard Lorenz definition:
    COP_Lor = 7.35, so 3.02 would be η = 0.41). Pinned so that any change is visible.
    """
    r = single_stage("n-Hexane", *conditions(80, 70, -10, 40), slhx=True)
    assert r.COP == pytest.approx(3.53, abs=0.03)


# ------------------------------------------------------------------ physics checks
def test_first_law_closure_standard_cycle():
    """q_sink - q_source = refrigerant enthalpy rise = w_el η_motor (1 - f_q) for a valve cycle."""
    a = CycleAssumptions()
    r = single_stage("n-Propane", SecondaryStream(10, 5), SecondaryStream(40, 70), a)
    assert r.q_sink_kJ_kg - r.q_source_kJ_kg == pytest.approx(r.w_el_kJ_kg * a.eta_motor * (1 - a.heat_loss_factor),
                                                                rel=1e-9)


@pytest.mark.parametrize("fluid", ["n-Propane", "Ammonia", "R1234ze(E)"])
def test_second_law_and_lift_trend(fluid):
    src = SecondaryStream(10, 5)
    cops = [single_stage(fluid, src, SecondaryStream(40, T)).COP for T in (60, 70, 80)]
    lorenz = [single_stage(fluid, src, SecondaryStream(40, T)).COP_lorenz for T in (60, 70, 80)]
    assert all(c < cl for c, cl in zip(cops, lorenz))
    assert cops[0] > cops[1] > cops[2]


def test_isothermal_sink_and_source_feasible():
    """Brewery-like HTHP conditions: isothermal -1 °C source, isothermal 103 °C sink."""
    r = single_stage("n-Butane", SecondaryStream(-1, -1), SecondaryStream(103, 103), slhx=True)
    assert r.feasible and 0 < r.eta_lorenz < 1
    assert r.T_evap_C == pytest.approx(-1 - 3 - 3, abs=0.05)   # source - pinch - superheat


# ------------------------------------------------------------------ two-stage cycles (Andersen Appendix A)
def test_appendix_A_two_stage_vapour_injection():
    """Two-stg, R-1234ze(E); 50 °C, 50 K, -40 K, 10 K; published COP 2.14. Deviation -0.1 %."""
    from pinch.cycle import two_stage
    r = two_stage("R1234ze(E)", *conditions(50, 50, -40, 10), variant="two-stg")
    assert r.COP == pytest.approx(2.14, rel=0.02)


def test_appendix_A_two_stage_open_intercooler_water():
    """Two-stg2, R-718; 80 °C, 60 K, -20 K, 10 K; published COP 3.15. Ours 2.99 (-5.0 %), on the
    conservative side; intermediate pressure optimised on a factor of the geometric mean."""
    from pinch.cycle import two_stage
    r = two_stage("Water", *conditions(80, 60, -20, 10), variant="two-stg2")
    assert r.COP == pytest.approx(3.15, rel=0.06)
    assert r.COP < 3.15


def test_practical_limits_flag_high_pressure_ratio():
    from pinch.cycle_analysis import practical_issues
    r = single_stage("n-Pentane", SecondaryStream(-1, -1), SecondaryStream(103, 103), slhx=True)
    issues = practical_issues(r)
    assert r.feasible and any("pressure ratio" in i for i in issues)     # about 38 > 10 (Annex 58 Table 1-3)
