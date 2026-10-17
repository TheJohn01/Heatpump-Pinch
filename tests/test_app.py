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
    s = compute(load_case(ROOT / "cases" / "brewery.json")).summary
    assert shown["Q̇h,min [kWh/hl]"] == f"{s['targets']['Qh_min']:.4g}"


def test_price_change_moves_ratio_and_persists_across_steps(brewery):
    at = _goto(brewery, STEPS[5])
    at.session_state["econ_electricity_price_EUR_per_kWh"] = 0.09
    at.run()
    _goto(at, STEPS[1])
    at = _goto(at, STEPS[5])
    assert any("1.76" in c.value for c in at.caption), [c.value for c in at.caption]
    delta = next(m for m in at.metric if m.label.startswith("Full design: break-even")).delta
    assert delta.startswith("+0.47"), delta          # 2.23 break-even (eta_L 0.50, DEA O&M) - 1.76 today
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
    saved = pd.read_csv(ROOT / "outputs" / "brewery" / "rq_consolidated.csv").iloc[0]
    assert rq1.value == f"{100 * saved['RQ1_HP_gas_share']:.1f} %"
    assert any("hl/year" in c.value for c in at.caption)           # A3: production condition shown
    assert any("HP1 = Warm-water HP" in c.value for c in at.caption)


def _dashboard_for(case, basis_on):
    def page(case, basis_on):
        import app_pages
        import streamlit as st
        app_pages.init_state()
        if st.session_state.choice != case:
            app_pages.load_inputs(case)
            if basis_on:
                st.session_state.basis_on = True
        app_pages.dashboard_page()
    at = st_testing.AppTest.from_function(page, args=(case, basis_on), default_timeout=300)
    at.run()
    _ok(at)
    return at


@pytest.mark.parametrize("case", ["spray_dryer", "milk_evaporator", "four_stream_process"])
def test_dashboard_computes_for_every_case(case):
    """Every case gets RQ1-RQ3 on the Dashboard (an assumed annual basis where none is published)."""
    at = _dashboard_for(case, basis_on=True)
    labels = [m.label for m in at.metric]
    assert any(lbl.startswith("RQ1") for lbl in labels) and any(lbl.startswith("RQ3") for lbl in labels)
    assert any("Today's site" in c.value for c in at.caption)
    assert len(at.dataframe) == 1


def test_dashboard_asks_for_a_basis_when_none_is_published():
    at = _dashboard_for("milk_evaporator", basis_on=False)
    assert any("annual basis" in i.value for i in at.info)
    assert not [m for m in at.metric if m.label.startswith("RQ1")]


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
    at = _case_app("milk_evaporator", "6 Economics")
    assert "Switch on the annual basis in step 1" in _texts(at)
    at = _case_app("milk_evaporator", "3 ΔTmin", h=float("nan"))   # coefficients cleared
    assert "film coefficient for every stream" in _texts(at)
    at = _case_app("milk_evaporator", "5 Retrofit")
    assert "No existing heat-exchanger network" in _texts(at)


def test_assumed_basis_runs_economics_and_is_labelled():
    at = _case_app("milk_evaporator", "6 Economics", basis_on=True)
    assert any(m.label.startswith("Full design: break-even") for m in at.metric), [m.label for m in at.metric]
    assert "No economic data in the source" in _texts(at)
    case = at.session_state["base_case"]
    assert at.session_state["basis"] == {"type": "power", "operating_hours_per_year": 8000.0}
    assert case.basis is None                      # the published case is untouched


def test_assumed_film_coefficients_run_supertargeting():
    at = _case_app("spray_dryer", "3 ΔTmin", basis_on=True, h=0.05)
    assert not any("film coefficient for every stream" in i.value for i in at.info)
    assert len(at.dataframe) >= 1                  # RQ2 table shown


def test_assumed_basis_recorded_in_provenance():
    from streamlit.testing.v1 import AppTest

    def page():
        import app_pages
        import streamlit as st
        app_pages.init_state()
        app_pages.load_inputs("four_stream_process")
        st.session_state.basis_on = True
        case, _ = app_pages.build_case()
        st.write(case.provenance.get("annual basis", "missing"))
    at = AppTest.from_function(page, default_timeout=120)
    at.run()
    _ok(at)
    assert any("assumed in the app" in m.value for m in at.markdown), [m.value for m in at.markdown]


def test_operating_hours_note_shown_for_dairy():
    at = _case_app("milk_evaporator", "1 Streams", basis_on=True)
    assert "upper bound" in _texts(at)


def test_extrapolated_heat_pump_cost_is_flagged():
    at = _case_app("four_stream_process", "6 Economics", basis_on=True)
    assert any("extrapolated beyond the catalogue" in w.value for w in at.warning), [w.value for w in at.warning]


def test_break_even_ratio_never_reached_is_shown_as_none():
    def page():
        import app_pages
        import streamlit as st
        app_pages.init_state()
        if st.session_state.choice != "spray_dryer":
            app_pages.load_inputs("spray_dryer")
            st.session_state.basis_on = True
            st.session_state.basis_value = 2000.0
            st.session_state.econ_electricity_price_EUR_per_kWh = 0.1135
        st.session_state.step = st.session_state.step_ctl = "6 Economics"
        app_pages.workflow_page()
    at = st_testing.AppTest.from_function(page, default_timeout=300)
    at.run()
    _ok(at)
    assert next(m for m in at.metric if m.label.startswith("Full design: break-even")).value == "none"


def test_retrofit_tab_shows_bracket_for_spray_dryer():
    at = _case_app("spray_dryer", "5 Retrofit")
    assert any("no heat recovery (published)" in h.value for h in at.subheader), [h.value for h in at.subheader]
    assert len(at.dataframe) >= 1


def test_upload_uses_catalogue_heat_pump_costs():
    """Uploaded tables are costed with the DEA catalogue classes (template), not the brewery function."""
    import app_pages
    from pinch.economics import load_economics
    from pinch.case import load_case
    c = load_case(app_pages.ROOT / "cases" / "TEMPLATE.json")
    p = load_economics(c.economics)
    assert p.heat_pump_cost_class(105.0) == ("hp_dea_2a", False)
    assert p.cost_functions["hp_dea_2a"].variable_om_EUR_per_MWh == 3.6


def test_educated_approximation_warning_shown():
    at = _case_app("brewery", "4 Heat pumps")
    assert any("educated approximation" in w.value for w in at.warning), [w.value for w in at.warning]
