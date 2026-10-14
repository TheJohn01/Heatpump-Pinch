"""Smoke tests of the Streamlit front end (streamlit.testing).

The browser-only paths (file upload, editing a table cell) are covered by
ui_smoke.py, which drives a real browser.
"""

import pandas as pd
import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from pinch.validation import ROOT

APP = str(ROOT / "app.py")
CASES = sorted(p.stem for p in (ROOT / "cases").glob("*.json") if p.stem != "TEMPLATE")
STEPS = ["1 Streams", "2 Targets", "3 ΔTmin", "4 Heat pumps", "5 Retrofit", "6 Economics"]


def _app():
    at = st_testing.AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def _goto(at, step):
    at.session_state["step"] = step
    at.session_state["step_ctl"] = step
    return at.run()


def _ok(at):
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]


@pytest.fixture(scope="module")
def brewery():
    return _app()


@pytest.mark.parametrize("step", STEPS)
def test_every_workflow_step_runs(brewery, step):
    _ok(_goto(brewery, step))


def test_targets_match_command_line(brewery):
    from analyse import compute
    from pinch.case import load_case
    at = _goto(brewery, STEPS[1])
    shown = {m.label: m.value for m in at.metric}
    s = compute(load_case(ROOT / "cases" / "brewery_padulles2026.json")).summary
    assert shown["Q̇h,min [kWh/hl]"] == f"{s['targets']['Qh_min']:.4g}"


def test_price_change_moves_ratio_and_persists_across_steps(brewery):
    at = _goto(brewery, STEPS[5])
    at.session_state["econ_electricity_price_EUR_per_kWh"] = 0.09
    at.run()
    _goto(at, STEPS[1])
    at = _goto(at, STEPS[5])
    assert any("1.76" in c.value for c in at.caption), [c.value for c in at.caption]
    delta = next(m for m in at.metric if m.label.startswith("RQ3")).delta
    assert delta.startswith("+0.95"), delta          # 2.71 break-even - 1.76 today
    at.session_state["econ_electricity_price_EUR_per_kWh"] = 0.1135
    at.run()


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("step", ["2 Targets", "4 Heat pumps", "6 Economics"])
def test_every_case_runs(case, step):
    at = st_testing.AppTest.from_function(_load_and_show, args=(case, step), default_timeout=180)
    at.run()
    _ok(at)


def _load_and_show(case, step):
    import app_pages
    import streamlit as st
    app_pages.init_state()
    if st.session_state.choice != case:
        app_pages.load_inputs(case)
    st.session_state.step = st.session_state.step_ctl = step
    app_pages.workflow_page()


def test_bad_stream_table_gives_message():
    at = _app()
    at.session_state["streams_df"] = pd.DataFrame({"stream": ["A"], "type": ["hot"], "T_in_C": [100]})
    at = _goto(at, STEPS[1])
    assert not at.exception
    assert any("missing columns" in e.value for e in at.error)


def _dashboard():
    import app_pages
    app_pages.dashboard_page()


def _sources():
    import app_pages
    app_pages.sources_page()


def test_dashboard_shows_saved_consolidated_table():
    at = st_testing.AppTest.from_function(_dashboard, default_timeout=180)
    at.run()
    _ok(at)
    rq1 = next(m for m in at.metric if m.label.startswith("RQ1"))
    saved = pd.read_csv(ROOT / "outputs" / "brewery_padulles2026" / "rq_consolidated.csv").iloc[0]
    assert rq1.value == f"{100 * saved['RQ1_gas_share']:.1f} %"


def test_sources_page_runs():
    at = st_testing.AppTest.from_function(_sources, default_timeout=180)
    at.run()
    _ok(at)
