"""Tests for stream loading, the Problem Table Algorithm and composite curves.

Order follows the project rules: four-stream textbook example first, then the
brewery published targets (Padullés et al., 2026).
"""

from pathlib import Path

import numpy as np
import pytest

from pinch import composite_curve, energy_balance, load_streams, problem_table, with_extra_shift
from pinch.validation import ROOT, computed_targets, load_references, run_case

REFS = load_references()


# ------------------------------------------------- Four-stream textbook example
def test_fourstream_targets():
    case = REFS["four_stream_process"]
    computed = computed_targets(run_case(case))
    for quantity, ref in case["targets"].items():
        assert computed[quantity] == pytest.approx(ref["value"], abs=ref["tolerance"]), quantity


def test_fourstream_full_cascade():
    case = REFS["four_stream_process"]
    table = run_case(case)
    np.testing.assert_allclose(table.T_star_C, case["T_star_C"])
    np.testing.assert_allclose(table.cascade_feasible, case["cascade_feasible"])


@pytest.mark.parametrize("case_name", ["northwestern_4stream", "milk_evaporator"])
def test_independent_published_targets(case_name):
    """Second textbook example and an industrial dairy case (Walmsley et al., 2024)."""
    case = REFS[case_name]
    computed = computed_targets(run_case(case))
    for quantity, ref in case["targets"].items():
        assert computed[quantity] == pytest.approx(ref["value"], abs=ref["tolerance"]), quantity


# ------------------------------------------------------------------------ Brewery
@pytest.mark.parametrize("case_name", ["brewery_base", "brewery_indirect"])
def test_brewery_published_targets(case_name):
    case = REFS[case_name]
    computed = computed_targets(run_case(case))
    for quantity, ref in case["targets"].items():
        assert computed[quantity] == pytest.approx(ref["value"], abs=ref["tolerance"]), quantity


def test_brewery_pinch_at_ambient():
    """Paper: pinch at the incoming water (ambient) temperature, 15 °C + 2 K shift."""
    table = run_case(REFS["brewery_base"])
    assert table.pinch_T_star_C == (17.0,)


# ---------------------------------------------------------------- Consistency
@pytest.mark.parametrize("case_name", ["four_stream_process", "northwestern_4stream", "brewery_base",
                                       "brewery_indirect", "milk_evaporator"])
def test_first_law_closure(case_name):
    """Qc_min - Qh_min must equal total hot load - total cold load."""
    case = REFS[case_name]
    streams = with_extra_shift(load_streams(ROOT / case["data_file"]), case["extra_shift_K"])
    table = problem_table(streams)
    balance = energy_balance(streams)
    assert table.Qc_min - table.Qh_min == pytest.approx(balance["net_surplus"], abs=1e-9)


def test_brewery_totals_match_table_2():
    balance = energy_balance(load_streams(ROOT / "data" / "brewery_streams.csv"))
    assert balance["Q_cold_total"] == pytest.approx(21.4)
    assert balance["Q_hot_total"] == pytest.approx(14.8)


def test_shifted_composites_touch_at_pinch():
    """Shifted hot and cold composites meet at the pinch (zero vertical gap)."""
    streams = load_streams(ROOT / "data" / "four_stream_process_streams.csv")
    table = problem_table(streams)
    H_hot, T_hot = composite_curve(streams, "hot")
    H_cold, T_cold = composite_curve(streams, "cold", H_offset=table.Qc_min)
    T_pinch = table.pinch_T_star_C[0]
    assert np.interp(T_pinch, T_hot, H_hot) == pytest.approx(np.interp(T_pinch, T_cold, H_cold))


def test_composite_end_enthalpies():
    streams = load_streams(ROOT / "data" / "four_stream_process_streams.csv")
    table = problem_table(streams)
    H_hot, _ = composite_curve(streams, "hot")
    H_cold, _ = composite_curve(streams, "cold", H_offset=table.Qc_min)
    assert H_hot[-1] == pytest.approx(61.5)
    assert H_cold[-1] - H_hot[-1] == pytest.approx(table.Qh_min)


# ------------------------------------------------------------ Input validation
def test_rejects_hot_stream_heating_up(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("stream,type,T_in_C,T_out_C,Q_kW,dT_shift_K\nH1,hot,50,100,10,5\n")
    with pytest.raises(ValueError, match="hot stream"):
        load_streams(bad)


def test_rejects_missing_load_column(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("stream,type,T_in_C,T_out_C,dT_shift_K\nH1,hot,100,50,5\n")
    with pytest.raises(ValueError, match="exactly one"):
        load_streams(bad)


def test_rejects_negative_extra_shift():
    streams = load_streams(ROOT / "data" / "four_stream_process_streams.csv")
    with pytest.raises(ValueError):
        with_extra_shift(streams, -1)


def test_brewery_reproduced_targets_pinned():
    """Supervisor review C4: reproduced values pinned exactly (the published comparison, with its known
    rounding gap in Q̇c, is reported separately by validate_targets.py)."""
    from pinch import load_streams, with_extra_shift, problem_table
    from pinch.validation import ROOT
    s = load_streams(ROOT / "data" / "brewery_streams.csv")
    t0, t2 = problem_table(s), problem_table(with_extra_shift(s, 2.0))
    assert t0.Qh_min == pytest.approx(10.042352941176471, abs=1e-9)
    assert t0.Qc_min == pytest.approx(3.4423529411764715, abs=1e-9)
    assert t0.pinch_T_star_C == (17.0,)
    assert t2.Qh_min == pytest.approx(10.48470588235294, abs=1e-9)
    assert t2.Qc_min == pytest.approx(3.8847058823529412, abs=1e-9)
    assert t2.pinch_T_star_C == (19.0,)
    # deviations from the published values (Sec. 4.1), reported, not hidden
    assert t0.Qc_min - 3.2 == pytest.approx(0.2424, abs=1e-4)
