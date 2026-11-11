"""Tests for non-continuous processes (``pinch.time_slices``): Time Slice and Time Average targets,
storage sizing, and the heat pump with storage loops of Stampfli et al. (2019).

Known answers: hand calculations, the continuous limit (both models equal the Problem Table), and the
published dairy case (Stampfli et al. 2019, Energy 182; Stampfli et al. 2018, CET 70, 1789).
"""

import pandas as pd
import pytest

import reproduce_stampfli2019 as rs
from pinch import load_streams, problem_table
from pinch.time_slices import (
    load_schedule,
    stampfli_cop,
    storage_for_constant_supply,
    storage_heat_pump,
    tam_targets,
    time_slices,
    tsm_targets,
)


def _schedule_csv(tmp_path, rows, unit_col="CP_kW_per_K"):
    cols = ["stream", "type", "T_in_C", "T_out_C", unit_col, "dT_shift_K", "t_start_h", "t_end_h"]
    p = tmp_path / "s.csv"
    pd.DataFrame(rows, columns=cols).to_csv(p, index=False)
    return p


def test_continuous_process_both_models_equal_the_problem_table(tmp_path):
    """Four-stream example, every stream running all day: TSM = TAM = Problem Table x 24 h."""
    d = pd.read_csv("data/four_stream_process_streams.csv").assign(t_start_h=0.0, t_end_h=24.0)
    p = tmp_path / "four.csv"
    d.to_csv(p, index=False)
    sched = load_schedule(p)
    pt = problem_table(load_streams("data/four_stream_process_streams.csv"))
    for t in (tsm_targets(sched), tam_targets(sched)):
        assert t["Qh_kWh"] == pytest.approx(24 * pt.Qh_min)
        assert t["Qc_kWh"] == pytest.approx(24 * pt.Qc_min)


def test_hand_case_storage_bounds(tmp_path):
    """Hot 100 -> 40 °C and cold 30 -> 90 °C, CP 1 kW/K each, ΔT_shift 5 K, hot 0-12 h, cold 12-24 h.
    No overlap in time: direct recovery is zero, TSM Qh = 60 kW x 12 h = 720 kWh. Averaged over the day
    the two match exactly in T*: TAM Qh = 0."""
    p = _schedule_csv(tmp_path, [("H", "hot", 100, 40, 1.0, 5, 0, 12), ("C", "cold", 30, 90, 1.0, 5, 12, 24)])
    sched = load_schedule(p)
    assert tsm_targets(sched)["Qh_kWh"] == pytest.approx(720.0)
    assert tam_targets(sched)["Qh_kWh"] == pytest.approx(0.0, abs=1e-9)
    assert [(s.t0_h, s.t1_h) for s in time_slices(sched)] == [(0.0, 12.0), (12.0, 24.0)]


def test_tam_never_needs_more_utility_than_tsm():
    sched = load_schedule(rs.DATA)
    assert tam_targets(sched)["Qh_kWh"] <= tsm_targets(sched)["Qh_kWh"] + 1e-6


def test_storage_for_constant_supply_hand_cases():
    """40 kW for 8 h in a 24 h cycle. Supply all day: 13.33 kW, storage 40 x 8 - 13.33 x 8 = 213.3 kWh.
    Supply only during the 8 h of demand: 40 kW, no storage."""
    r = storage_for_constant_supply([0.0, 40.0, 0.0], [8.0, 8.0, 8.0])
    assert r["supply_kW"] == pytest.approx(40.0 / 3)
    assert r["storage_kWh"] == pytest.approx(320.0 - 8 * 40.0 / 3)
    r = storage_for_constant_supply([0.0, 40.0, 0.0], [8.0, 8.0, 8.0], operating_h=8.0, start_h=8.0)
    assert r["supply_kW"] == pytest.approx(40.0) and r["storage_kWh"] == pytest.approx(0.0, abs=1e-9)


def test_cop_definition():
    """ζ Tco / (Tco - Tev) with Tco = 33.8 + 12.5 °C and Tev = 7.93 - 12.5 °C (Eqs 5-7)."""
    Tco, Tev = 33.8 + 12.5 + 273.15, 7.93 - 12.5 + 273.15
    assert stampfli_cop(33.8, 7.93, 10.0) == pytest.approx(0.35 * Tco / (Tco - Tev))


def test_stampfli2019_reproduction():
    """Published values within their rounding: Tco 46.26 °C, Tev -4.56 °C, COP 2.2 (CET 2018), condenser
    storage 1.35 MWh and, at the paper's T*ev = 8.3 °C, evaporator storage 0.68 MWh (Energy 2019)."""
    sched = load_schedule(rs.DATA)
    hp = storage_heat_pump(sched, 33.8, 10.0)
    assert hp.T_co_C == pytest.approx(46.26, abs=0.05)
    assert hp.T_ev_C == pytest.approx(-4.56, abs=0.02)
    assert hp.COP == pytest.approx(2.2, abs=0.01)
    assert hp.hot_storage_kWh / 1000 == pytest.approx(1.35, abs=0.015)
    assert hp.cold_side_imbalance_kWh == pytest.approx(0.0, abs=1e-6)        # Eq. 9 satisfied
    assert hp.Q_condenser_kW - hp.Q_evaporator_kW == pytest.approx(0.9 * hp.P_el_kW)   # Eq. 8
    at_83 = storage_heat_pump(sched, 33.8, 10.0, T_ev_star_C=8.3)
    assert at_83.cold_storage_kWh / 1000 == pytest.approx(0.68, abs=0.015)


def test_shorter_operation_needs_a_larger_heat_pump():
    """Same daily heat in half the time: twice the condenser duty (Stampfli et al. 2019, Fig. 10 driver)."""
    sched = load_schedule(rs.DATA)
    full = storage_heat_pump(sched, 33.8, 10.0)
    half = storage_heat_pump(sched, 33.8, 10.0, operating_h=12.0, start_h=6.0)
    assert half.Q_condenser_kW == pytest.approx(2 * full.Q_condenser_kW)
    assert half.heat_per_cycle_kWh == pytest.approx(full.heat_per_cycle_kWh)


def test_table1_transcription():
    """ΔH and kWh of Table 1 (Stampfli et al. 2019) from CP, temperatures and times; wash water is the
    one mismatch printed in the source (242.9 vs 260.25 kW)."""
    t = rs.table1_consistency().set_index("stream")
    assert t.loc["Cream heating C3", "dH_kW"] == pytest.approx(1952.4)
    assert t.loc["Cream heating C3", "dH_kWh"] == pytest.approx(14643.0)
    assert t.loc["Buttermilk cooling H4", "dH_kWh"] == pytest.approx(7533.0)
    assert t.loc["Treated cream cooling H1", "dH_kWh"] == pytest.approx(5370.0)
    assert t.loc["Alkaline detergent solution C9", "dH_kWh"] == pytest.approx(961.40, abs=0.1)
    assert t.loc["Wash water heating C6", "dH_kW"] == pytest.approx(242.9)


def test_schedule_input_checks(tmp_path):
    with pytest.raises(ValueError, match="power"):
        load_schedule(_schedule_csv(tmp_path, [("H", "hot", 100, 40, 1.0, 5, 0, 12)], "CP_kWh_per_hl_per_K"))
    with pytest.raises(ValueError, match="t_start_h < t_end_h"):
        load_schedule(_schedule_csv(tmp_path, [("H", "hot", 100, 40, 1.0, 5, 12, 6)]))
