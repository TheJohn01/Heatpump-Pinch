"""Tests for the plant-data tools (workflow steps 1-2): segmented streams, Excel input, data reconciliation,
stream-data uncertainty and targets with restricted matches.

Known answers: hand calculations, the Problem Table targets of the validated cases (the restricted-match
LP must reproduce them when nothing is restricted), and physical bounds.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from pinch import load_streams, problem_table, with_extra_shift
from pinch.case import _parse_restrictions
from pinch.reconciliation import (
    Exchanger,
    Measurement,
    reconcile_linear,
    reconcile_network,
)
from pinch.restricted_matches import CU, HU, restricted_targets
from pinch.streams import Stream, StreamSet, segments_from_TH, streams_from_frame
from pinch.uncertainty import target_uncertainty

DATA = "data/"
CASES = [("four_stream_process_streams.csv", 0.0, 7.5, 10.0), ("northwestern_4stream.csv", 0.0, 2900.0, 600.0),
         ("brewery_streams.csv", 0.0, None, None), ("brewery_streams.csv", 2.0, None, None),
         ("milk_evaporator_streams.csv", 0.0, None, None), ("spray_dryer_streams.csv", 0.0, None, None)]


def _rows(*rows):
    cols = ["stream", "type", "T_in_C", "T_out_C", "Q_kW", "dT_shift_K", "segment_of"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


# ---------------------------------------------------------------- segmented streams
def test_segments_give_the_same_targets_as_the_whole_stream():
    """A constant-CP stream split into two segments must not change the targets (four-stream example)."""
    whole = load_streams(DATA + "four_stream_process_streams.csv")
    s = whole.streams[0]
    mid = (s.T_in_C + s.T_out_C) / 2
    a = Stream("A", s.kind, s.T_in_C, mid, s.Q / 2, s.dT_shift_K, parent=s.name)
    b = Stream("B", s.kind, mid, s.T_out_C, s.Q / 2, s.dT_shift_K, parent=s.name)
    split = StreamSet((a, b) + whole.streams[1:], whole.energy_unit)
    t0, t1 = problem_table(whole), problem_table(split)
    assert t1.Qh_min == pytest.approx(t0.Qh_min) and t1.Qc_min == pytest.approx(t0.Qc_min)


def test_segment_table_is_validated():
    ok = streams_from_frame(_rows(("h1a", "hot", 150, 100, 50, 5, "H1"), ("h1b", "hot", 100, 50, 100, 5, "H1"),
                                  ("c1", "cold", 40, 140, 120, 5, "")))
    assert [s.parent for s in ok.streams] == ["H1", "H1", None]
    assert ok.streams[1].CP == pytest.approx(2.0)                      # the CP changes along the stream
    with pytest.raises(ValueError, match="do not join"):
        streams_from_frame(_rows(("h1a", "hot", 150, 100, 50, 5, "H1"), ("h1b", "hot", 90, 50, 80, 5, "H1")))
    with pytest.raises(ValueError, match="mix hot and cold"):
        streams_from_frame(_rows(("a", "hot", 150, 100, 50, 5, "X"), ("b", "cold", 100, 150, 50, 5, "X")))
    with pytest.raises(ValueError, match="same name as the parent"):
        streams_from_frame(_rows(("H1", "hot", 150, 100, 50, 5, ""), ("h1b", "hot", 100, 50, 50, 5, "H1")))


def test_segments_from_TH():
    T = np.linspace(150.0, 50.0, 41)
    linear = segments_from_TH("x", "hot", T, 2.0 * (150.0 - T), 5.0)
    assert len(linear) == 1 and linear[0].parent is None and linear[0].CP == pytest.approx(2.0)

    H = (150.0 - T) + 0.004 * (150.0 - T) ** 2                        # CP rises as the stream cools
    for tol in (2.0, 1.0, 0.25):
        segs = segments_from_TH("x", "hot", T, H, 5.0, max_error_K=tol)
        assert sum(s.Q for s in segs) == pytest.approx(H[-1])          # total load preserved
        assert all(a.T_out_C == b.T_in_C for a, b in zip(segs[:-1], segs[1:]))
        for Tk, Hk in zip(T, H):                                       # every table point within tolerance
            seg = next(s for s in segs if s.T_out_C <= Tk <= s.T_in_C)
            H0 = sum(s.Q for s in segs[:segs.index(seg)])
            assert abs(seg.T_in_C - (Hk - H0) / seg.CP - Tk) <= tol + 1e-9
    assert len(segments_from_TH("x", "hot", T, H, 5.0, 0.25)) > len(segments_from_TH("x", "hot", T, H, 5.0, 2.0))
    with pytest.raises(ValueError, match="fall"):
        segments_from_TH("x", "hot", T[::-1], H, 5.0)


def test_excel_input_matches_csv(tmp_path):
    pytest.importorskip("openpyxl")
    csv = load_streams(DATA + "brewery_streams.csv")
    path = tmp_path / "streams.xlsx"
    with pd.ExcelWriter(path) as w:
        pd.DataFrame({"note": ["cover sheet"]}).to_excel(w, sheet_name="readme", index=False)
        pd.read_csv(DATA + "brewery_streams.csv").to_excel(w, sheet_name="streams", index=False)
    xl = load_streams(path)
    assert xl.energy_unit == csv.energy_unit
    assert problem_table(xl).Qh_min == pytest.approx(problem_table(csv).Qh_min)


# ---------------------------------------------------------------- data reconciliation
def test_weighted_mean_of_two_measurements():
    """x1 = 10 (σ 1), x2 = 12 (σ 2), x1 = x2: inverse-variance mean (10/1 + 12/4) / (1 + 1/4) = 10.4."""
    x = reconcile_linear([10.0, 12.0], [1.0, 2.0], [[1.0, -1.0]])
    assert x == pytest.approx([10.4, 10.4])


def test_fixed_value_does_not_move():
    x = reconcile_linear([10.0, 12.0], [0.0, 2.0], [[1.0, -1.0]])
    assert x == pytest.approx([10.0, 10.0])


def _network(values, sigma_T=1.0, sigma_CP=0.05):
    """Hot H (CP_H) cools through E1 then E2; cold C1 is heated in E1, cold C2 in E2."""
    ex = [Exchanger("E1", "CP_H", "TH0", "TH1", "CP_C1", "TC1i", "TC1o"),
          Exchanger("E2", "CP_H", "TH1", "TH2", "CP_C2", "TC2i", "TC2o")]
    m = {k: Measurement(v, sigma_CP * v if k.startswith("CP") else sigma_T) for k, v in values.items()}
    return ex, m


TRUE = {"CP_H": 2.0, "TH0": 150.0, "TH1": 110.0, "TH2": 70.0, "CP_C1": 1.6, "TC1i": 40.0, "TC1o": 90.0,
        "CP_C2": 4.0, "TC2i": 20.0, "TC2o": 40.0}   # E1: 2 x 40 = 1.6 x 50 = 80; E2: 2 x 40 = 4 x 20 = 80


def test_reconciliation_closes_balances_and_keeps_true_data():
    ex, m = _network(TRUE)
    r = reconcile_network(m, ex)
    assert r.max_balance_residual < 1e-9
    assert all(abs(r.values[k] - v) < 1e-9 for k, v in TRUE.items())   # already consistent: nothing moves
    assert r.duties(ex) == pytest.approx({"E1": 80.0, "E2": 80.0})


def test_reconciliation_reduces_error_on_noisy_data():
    """Seeded noise on consistent data: after reconciliation the balances close and, averaged over seeds,
    the values are closer to the truth than the measurements."""
    raw_err, rec_err = [], []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        noisy = {k: v + rng.normal(0, 0.05 * v if k.startswith("CP") else 1.0) for k, v in TRUE.items()}
        ex, m = _network(noisy)
        for k in noisy:                                   # sigma relative to the true value, as generated
            if k.startswith("CP"):
                m[k] = Measurement(noisy[k], 0.05 * TRUE[k])
        r = reconcile_network(m, ex)
        assert r.max_balance_residual < 1e-8
        raw_err.append(sum(((noisy[k] - v) / m[k].sigma) ** 2 for k, v in TRUE.items()))
        rec_err.append(sum(((r.values[k] - v) / m[k].sigma) ** 2 for k, v in TRUE.items()))
    assert np.mean(rec_err) < np.mean(raw_err)


def test_iterative_method_of_yong_et_al_puts_the_whole_correction_on_the_cps():
    """Yong et al. (2016), Fig. 1, CP model first: it closes every balance with T at the measured values,
    so the T model changes nothing (the inaccuracy the authors acknowledge)."""
    biased = dict(TRUE, TC1o=TRUE["TC1o"] + 3.0)
    ex, m = _network(biased)
    it = reconcile_network(m, ex, method="iterative")
    assert it.max_balance_residual < 1e-9
    assert all(it.adjustments[k] == pytest.approx(0.0, abs=1e-9) for k in TRUE if k.startswith("T"))
    sim = reconcile_network(m, ex)
    assert sim.test_statistic < it.test_statistic        # the simultaneous solution is the least-squares one
    assert sim.adjustments["TC1o"] < 0                   # and it pulls the faulty reading back


def test_gross_error_is_flagged():
    biased = dict(TRUE, TC1o=TRUE["TC1o"] + 15.0)          # 15 sigma error on one thermometer
    ex, m = _network(biased)
    assert reconcile_network(m, ex).gross_error_suspected
    ex, m = _network(TRUE)
    assert not reconcile_network(m, ex).gross_error_suspected


def test_reconciliation_input_checks():
    ex, m = _network(TRUE)
    del m["TH1"]
    with pytest.raises(ValueError, match="no measurement"):
        reconcile_network(m, ex)
    with pytest.raises(ValueError):
        Measurement(1.0, -0.1)


# ---------------------------------------------------------------- stream-data uncertainty
def test_zero_uncertainty_returns_the_nominal_targets():
    s = load_streams(DATA + "brewery_streams.csv")
    u = target_uncertainty(s, heat_flow_relative=0.0, temperature_K=0.0, n=20)
    assert u.summary.loc["Qh_min", "std"] == pytest.approx(0.0, abs=1e-12)
    assert u.summary.loc["Qh_min", "mean"] == pytest.approx(problem_table(s).Qh_min)


def test_linear_propagation_through_a_load_above_the_pinch():
    """Lautering (cold, T* 17-77 °C) lies wholly above the brewery pinch (T* 17 °C), so dQh,min/dQ = 1:
    σ 1 % on its 6.0 kWh/hl load alone gives σ(Qh,min) = 0.06 kWh/hl."""
    s = load_streams(DATA + "brewery_streams.csv")
    u = target_uncertainty(s, heat_flow_relative={x.name: (0.01 if x.name == "Lautering/Filtering" else 0.0)
                                                  for x in s.streams}, temperature_K=0.0, n=2000)
    assert u.summary.loc["Qh_min", "std"] == pytest.approx(0.06, rel=0.03)
    assert u.r2["Qh_min"] > 0.999
    assert u.src.loc["Lautering/Filtering: Q", "Qh_min"] == pytest.approx(1.0, abs=1e-3)


def test_uncertainty_is_deterministic_and_reports_mc_error():
    s = load_streams(DATA + "four_stream_process_streams.csv")
    a = target_uncertainty(s, n=300, seed=3)
    b = target_uncertainty(s, n=300, seed=3)
    pd.testing.assert_frame_equal(a.samples, b.samples)
    r = a.summary.loc["Qh_min"]
    assert r["MCerr"] == pytest.approx(r["std"] / math.sqrt(300))
    assert a.important_inputs()


def test_latent_streams_move_as_a_whole():
    s = load_streams(DATA + "brewery_streams.csv")
    u = target_uncertainty(s, n=50)
    assert "Wortboiling (boiling): T" in u.samples and "Wortboiling (boiling): T_in" not in u.samples
    assert "Wortcooling: T_in" in u.samples and "Wortcooling: T_out" in u.samples


# ---------------------------------------------------------------- restricted matches
@pytest.mark.parametrize("name, extra, Qh, Qc", CASES)
def test_no_restrictions_reproduce_the_problem_table(name, extra, Qh, Qc):
    s = with_extra_shift(load_streams(DATA + name), extra)
    t, r = problem_table(s), restricted_targets(s, {})
    assert r.Qh_min == pytest.approx(t.Qh_min, abs=1e-9 * max(1, t.Qh_min))
    assert r.Qc_min == pytest.approx(t.Qc_min, abs=1e-9 * max(1, t.Qh_min))
    if Qh is not None:
        assert (r.Qh_min, r.Qc_min) == pytest.approx((Qh, Qc))


def test_all_process_matches_forbidden():
    s = load_streams(DATA + "brewery_streams.csv")
    r = restricted_targets(s, {(h.name, c.name): 0.0 for h in s.hot for c in s.cold})
    assert r.Qh_min == pytest.approx(sum(c.Q for c in s.cold))
    assert r.Qc_min == pytest.approx(sum(h.Q for h in s.hot))


def _two_by_two():
    rows = [("H1", "hot", 200, 100, 100, 5), ("H2", "hot", 200, 100, 100, 5),
            ("C1", "cold", 50, 150, 100, 5), ("C2", "cold", 50, 150, 100, 5)]
    return streams_from_frame(pd.DataFrame(rows, columns=["stream", "type", "T_in_C", "T_out_C", "Q_kW", "dT_shift_K"]))


def test_hand_calculated_restrictions():
    """Two identical hot (200 -> 100 °C, 100 kW) and cold (50 -> 150 °C, 100 kW) streams, ΔT_shift 5 K.
    Unrestricted: Qh = 0. H1 barred from both colds: H2's 100 kW is all that is recovered, Qh = 100.
    H1 -> C1 at most 30 kW, H1 -> C2 barred: Qh = 200 - 100 - 30 = 70."""
    s = _two_by_two()
    assert restricted_targets(s, {}).Qh_min == pytest.approx(0.0, abs=1e-9)
    r = restricted_targets(s, {("H1", "C1"): 0, ("H1", "C2"): 0})
    assert (r.Qh_min, r.Qc_min) == pytest.approx((100.0, 100.0))
    assert r.matches[("H1", CU)] == pytest.approx(100.0)
    r = restricted_targets(s, {("H1", "C1"): 30, ("H1", "C2"): 0})
    assert r.Qh_min == pytest.approx(70.0) and r.penalty == pytest.approx(70.0)
    assert r.matches[("H1", "C1")] == pytest.approx(30.0)


def test_utility_restrictions():
    """Wort boiling (T* 102-103 °C) lies above every hot stream (highest T* 99 °C): without the hot
    utility it cannot be heated at all."""
    s = load_streams(DATA + "brewery_streams.csv")
    with pytest.raises(ValueError, match="no feasible"):
        restricted_targets(s, {(HU, "Wortboiling (boiling)"): 0})
    with pytest.raises(ValueError, match="unknown stream"):
        restricted_targets(s, {("nope", "CIP"): 0})
    s2 = _two_by_two()
    with pytest.raises(ValueError, match="no feasible"):                # H1 with no outlet at all
        restricted_targets(s2, {("H1", "C1"): 0, ("H1", "C2"): 0, ("H1", CU): 0})


def test_case_file_restrictions_need_a_reason():
    assert _parse_restrictions([{"hot": "A", "cold": "B", "reason": "hygiene zone"}], "x") == (("A", "B", 0.0, "hygiene zone"),)
    with pytest.raises(ValueError, match="reason"):
        _parse_restrictions([{"hot": "A", "cold": "B"}], "x")


def test_brewery_plant_data_check():
    """scripts/checks/plant_data_check.py on the brewery: nominal targets equal the validated ones, the Qh,min ranking is
    led by the wort-cooling load, and the three hot streams above the pinch are the only ones whose
    isolation costs hot utility."""

    from scripts.checks import plant_data_check
    root = plant_data_check.ROOT
    ref = json.loads((root / "data" / "reference_targets.json").read_text(encoding="utf-8"))
    res = plant_data_check.check(root / "cases" / "brewery.json")
    u = res["uncertainty"]
    assert u.nominal["Qh_min"] == pytest.approx(problem_table(load_streams(root / "data" / "brewery_streams.csv")).Qh_min)
    assert u.src["Qh_min"].idxmax() == "Wortcooling: Q"
    iso = res["isolated"].set_index("stream")["penalty"]
    assert set(iso[iso > 1e-9].index) == {"Wortcooling", "Boiloff condensation", "Condensate cooling"}
    assert iso["Boiloff condensation"] == pytest.approx(2.4)             # its whole latent load
    assert ref is not None
