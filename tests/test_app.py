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


# ---------------------------------------------------------------- cases without published annual data
def _case_app(case, step, basis_on=None, h=None):
    """Load a case, optionally switch the annual basis on and fill film coefficients, show a step."""
    def page(case, step, basis_on, h):
        import app_pages
        import streamlit as st
        app_pages.init_state()
        if st.session_state.choice != case:
            app_pages.load_inputs(case)
            if basis_on is not None:
                st.session_state.basis_on = basis_on
            if h is not None:
                st.session_state.streams_df[app_pages.H_COLUMN] = h
        st.session_state.step = st.session_state.step_ctl = step
        app_pages.workflow_page()
    at = st_testing.AppTest.from_function(page, args=(case, step, basis_on, h), default_timeout=300)
    at.run()
    _ok(at)
    return at


def _texts(at):
    return " ".join([i.value for i in at.info] + [c.value for c in at.caption])


def test_case_without_basis_explains_what_is_missing():
    at = _case_app("walmsley2024_milk_evaporator", "6 Economics")
    assert "Switch on the annual basis in step 1" in _texts(at)
    at = _case_app("walmsley2024_milk_evaporator", "3 ΔTmin", h=float("nan"))   # coefficients cleared
    assert "film coefficient for every stream" in _texts(at)
    at = _case_app("walmsley2024_milk_evaporator", "5 Retrofit")
    assert "No existing heat-exchanger network" in _texts(at)


def test_assumed_basis_runs_economics_and_is_labelled():
    at = _case_app("walmsley2024_milk_evaporator", "6 Economics", basis_on=True)
    assert any(m.label.startswith("RQ3") for m in at.metric), [m.label for m in at.metric]
    assert "No economic data in the source" in _texts(at)
    case = at.session_state["base_case"]
    assert at.session_state["basis"] == {"type": "power", "operating_hours_per_year": 8000.0}
    assert case.basis is None                      # the published case is untouched


def test_assumed_film_coefficients_run_supertargeting():
    at = _case_app("walmsley2024_spray_dryer", "3 ΔTmin", basis_on=True, h=0.05)
    assert not any("film coefficient for every stream" in i.value for i in at.info)
    assert len(at.dataframe) >= 1                  # RQ2 table shown


def test_assumed_basis_recorded_in_provenance():
    import app_pages
    from streamlit.testing.v1 import AppTest

    def page():
        import app_pages
        import streamlit as st
        app_pages.init_state()
        app_pages.load_inputs("fourstream_example")
        st.session_state.basis_on = True
        case, _ = app_pages.build_case()
        st.write(case.provenance.get("annual basis", "missing"))
    at = AppTest.from_function(page, default_timeout=120)
    at.run()
    _ok(at)
    assert any("assumed in the app" in m.value for m in at.markdown), [m.value for m in at.markdown]


def test_operating_hours_note_shown_for_dairy():
    at = _case_app("walmsley2024_milk_evaporator", "1 Streams", basis_on=True)
    assert "upper bound" in _texts(at)


def test_extrapolated_heat_pump_cost_is_flagged():
    at = _case_app("fourstream_example", "6 Economics", basis_on=True)
    assert any("extrapolated beyond the catalogue" in w.value for w in at.warning), [w.value for w in at.warning]


def test_break_even_ratio_never_reached_is_shown_as_none():
    def page():
        import app_pages
        import streamlit as st
        app_pages.init_state()
        if st.session_state.choice != "walmsley2024_spray_dryer":
            app_pages.load_inputs("walmsley2024_spray_dryer")
            st.session_state.basis_on = True
            st.session_state.basis_value = 2000.0
            st.session_state.econ_electricity_price_EUR_per_kWh = 0.1135
        st.session_state.step = st.session_state.step_ctl = "6 Economics"
        app_pages.workflow_page()
    at = st_testing.AppTest.from_function(page, default_timeout=300)
    at.run()
    _ok(at)
    assert next(m for m in at.metric if m.label.startswith("RQ3")).value == "none"
