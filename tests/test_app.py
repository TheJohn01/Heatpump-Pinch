"""Smoke tests of the Streamlit front end (streamlit.testing): every published case
runs without an exception, and the numbers shown match the command-line results."""

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from pinch.validation import ROOT

APP = str(ROOT / "app.py")
CASES = sorted(p.stem for p in (ROOT / "cases").glob("*.json") if p.stem != "TEMPLATE")


def _run(case: str):
    at = st_testing.AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.sidebar.selectbox[0].set_value(case).run()
    return at


@pytest.mark.parametrize("case", CASES)
def test_every_case_runs(case):
    at = _run(case)
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]


def test_brewery_numbers_match_command_line():
    from analyse import compute
    from pinch.case import load_case
    at = _run("brewery_padulles2026")
    shown = {m.label: m.value for m in at.metric}
    s = compute(load_case(ROOT / "cases" / "brewery_padulles2026.json")).summary
    assert shown["Q̇h,min [kWh/hl]"] == f"{s['targets']['Qh_min']:.4g}"
    rq1 = s["economics"]["RQ1"]["max_fraction_with_payback_below_threshold"]
    assert shown["RQ1: share with payback ≤ 5 y"] == f"{100 * rq1:.1f} %"


def test_out_of_range_input_does_not_crash():
    at = _run("fourstream_example")
    at.sidebar.slider[0].set_value(0.55).run()
    at.sidebar.number_input[0].set_value(400.0).run()   # source far above the process: message or result, no crash
    assert not at.exception, at.exception
