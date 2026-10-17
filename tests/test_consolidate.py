"""Consolidated RQ1-RQ3 table: base row against the retrofit results and hand checks."""

import pytest

from pinch.validation import ROOT


@pytest.fixture(scope="module")
def table():
    import consolidate_rq
    return consolidate_rq.consolidate(ROOT / "cases" / "brewery.json").set_index("sensitivity")


def test_base_row_matches_retrofit_and_hand_check(table):
    b = table.loc["Base case"]
    # RQ1 (A1): heat pumps judged as increments over the heat-recovery retrofit N1, from the retrofit table
    # at eta_L 0.50: warm-water heat pump (1,137,325 - 55,972) EUR / (302,562 - 50,404) EUR/year = 4.29 y
    assert b["HP1_incremental_payback_y"] == pytest.approx((1_137_325 - 55_972) / (302_562 - 50_404), abs=0.01)
    # its share of today's gas: 1 - 3.0/11.3 (after) minus 1 - 10.4847/11.3 (heat recovery) = 0.6624
    assert b["RQ1_HP_gas_share"] == pytest.approx((10.4847 - 3.0) / 11.3, abs=1e-3)
    assert b["HR_retrofit_gas_share"] == pytest.approx(1 - 10.4847 / 11.3, abs=1e-3)
    # A2: the HTHP's COP (1.81 at eta_L 0.50) is below the break-even COP p_el x eta_boiler / p_gas = 1.87,
    # so its increment loses money; capex 520,000 + 600 x 375 kW (3.0 kWh/hl x 1e6 hl / 8000 h) = 745,000
    assert 0.1135 * 0.845 / 0.0512 == pytest.approx(1.873, abs=1e-3)
    assert b["HP2_incremental_payback_y"] == float("inf")
    assert b["RQ3_ratio_HP2"] < b["price_ratio"] < b["RQ3_ratio_HP1"]
    # A4: flat optimum reported as a range
    assert b["RQ2_dTmin_within_1pct_K"] == "0.08-2"
    # the published eta_L 0.55 reproduces the supervisor's decomposition (HTHP 291 y, NPV -0.73 M€)
    p = table.loc["Lorenz efficiency 0.55 (paper's value)"]
    assert p["HP2_incremental_payback_y"] == pytest.approx(291, abs=1)
    assert p["HP1_incremental_payback_y"] == pytest.approx(3.92, abs=0.01)


def test_directions_of_sensitivities(table):
    base = table.loc["Base case", "RQ3_ratio_HP1"]
    # more efficient boiler -> less gas saved -> lower break-even ratio
    assert table.loc["Boiler efficiency 1.0 (bound)", "RQ3_ratio_HP1"] < base
    # fixed heat pump costs: larger site -> higher break-even ratio
    r = [table.loc[f"Production {x} Mhl/year", "RQ3_ratio_HP1"] for x in ("0.25", "0.5")] + \
        [base, table.loc["Production 1.5 Mhl/year", "RQ3_ratio_HP1"]]
    assert r == sorted(r)
    # batch: a larger installed HTHP lowers its break-even ratio and leaves the warm-water heat pump unchanged
    F = [table.loc[f"Batch: HTHP sized for the boil window, F = {x}", "RQ3_ratio_HP2"] for x in ("1.14", "1.75", "3.0")]
    assert F == sorted(F, reverse=True) and F[0] < table.loc["Base case", "RQ3_ratio_HP2"]
    assert table.loc["Batch: HTHP sized for the boil window, F = 3.0", "RQ3_ratio_HP1"] == pytest.approx(base)
    # dearer area -> larger optimal dTmin is tested in test_area; here: no credit -> cheaper cold utility -> larger dTmin
    assert table.loc["No refrigeration credit", "RQ2_dTmin_opt_K"] >= table.loc["Base case", "RQ2_dTmin_opt_K"]


def test_one_sensitivity_list(table):
    """Audit 1.1: the consolidated table and the grass-roots table read the same list in the case file,
    so a label means one change everywhere (the grass-roots table uses its 'econ' rows)."""
    from pinch.case import load_case
    case = load_case(ROOT / "cases" / "brewery.json")
    labels = [s.label for s in case.sensitivities]
    rows = [r for r in table.index if r not in ("Base case", "No ambient source: heat pumps limited to the refrigeration heat")]
    assert rows == labels                                   # every row, in the case-file order, nothing else


def test_old_scenario_block_is_rejected(tmp_path):
    import json
    from pinch.case import load_case
    raw = json.loads((ROOT / "cases" / "four_stream_process.json").read_text(encoding="utf-8"))
    raw["stream_file"] = str(ROOT / "data" / "four_stream_process_streams.csv")
    raw["economics"]["scenarios"] = {"x": {"boiler_efficiency": 1.0}}
    f = tmp_path / "old.json"
    f.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="sensitivities"):
        load_case(f)


@pytest.mark.parametrize("bad", [
    [{"label": "a", "kind": "unknown", "value": 1}],
    [{"label": "a", "kind": "eta", "value": "0.5"}],
    [{"label": "a", "kind": "no_om", "value": 1}],
    [{"label": "a", "kind": "econ", "value": {}}, {"label": "a", "kind": "eta", "value": 0.5}],
])
def test_sensitivity_rows_are_validated(bad):
    from pinch.sensitivity import parse_sensitivities
    with pytest.raises(ValueError):
        parse_sensitivities(bad)


# ------------------------------------------------- every case (pinch.research_questions)
def _case(name, hours=8000):
    from dataclasses import replace
    from pinch.case import load_case
    c = load_case(ROOT / "cases" / f"{name}.json")
    return c if c.basis is not None else replace(c, basis={"type": "power", "operating_hours_per_year": hours})


@pytest.mark.parametrize("name", ["spray_dryer", "milk_evaporator", "four_stream_process"])
def test_every_case_has_rq_answers(name):
    import consolidate_rq
    df = consolidate_rq.consolidate(_case(name))
    b = df.iloc[0]
    assert b["sensitivity"] == "Base case" and 0.0 <= b["RQ1_HP_gas_share"] <= 1.0
    assert isinstance(b["HP1_name"], str) and b["RQ3_ratio_HP1"] == b["RQ3_ratio_HP1"]
    # HP1 has the highest COP: units are numbered in the order the electrification curve adds them
    from pinch import load_streams, with_extra_shift
    from pinch.economic_analysis import _params_and_converter
    from pinch.research_questions import build_site
    c = _case(name)
    st = with_extra_shift(load_streams(c.stream_file), c.extra_shift_K)
    site = build_site(c, st, _params_and_converter(c, st.energy_unit)[1])
    assert [u.COP for u in site.units] == sorted((u.COP for u in site.units), reverse=True)


def test_baseline_follows_the_published_status():
    """Spray dryer: the source says the plant recovers no heat -> today's site has none and the heat-recovery step
    is a new network at the target. Milk evaporator (heat-integrated, exchangers unknown) -> site at the target."""
    import consolidate_rq
    sd = consolidate_rq.consolidate(_case("spray_dryer")).iloc[0]
    me = consolidate_rq.consolidate(_case("milk_evaporator")).iloc[0]
    assert sd["todays_site"].startswith("no heat recovery") and sd["HR_retrofit_gas_share"] > 0
    assert me["todays_site"].startswith("heat recovery at the energy target") and me["HR_retrofit_gas_share"] != me["HR_retrofit_gas_share"]


def test_econ_override_keeps_other_cost_function_fields():
    """A row that changes the cost functions' capital terms keeps their O&M (it used to drop them, which made the
    'hot-water piping' rows pay back faster than the base case)."""
    import consolidate_rq
    df = consolidate_rq.consolidate(_case("milk_evaporator")).set_index("sensitivity")
    base, piping = df.loc["Base case"], df.loc["with hot-water piping (indirect cost)"]
    assert piping["HP1_incremental_payback_y"] > base["HP1_incremental_payback_y"]
    assert piping["HP1_incremental_NPV_MEUR"] < base["HP1_incremental_NPV_MEUR"]


def test_source_limited_row_needs_a_reachable_refrigeration_source():
    """Milk evaporator sources sit at ambient (15 °C): with no ambient source the heat pumps have nothing to take."""
    import consolidate_rq
    df = consolidate_rq.consolidate(_case("milk_evaporator")).set_index("sensitivity")
    row = df.loc["No ambient source: heat pumps limited to the refrigeration heat"]
    assert row["RQ1_HP_gas_share"] == 0.0 and row["HP1_incremental_payback_y"] != row["HP1_incremental_payback_y"]


def test_rq2_needs_a_sourced_cost_law():
    """The spray dryer has only a cost sweep (no sourced exchanger cost law): RQ2 is n/a, not the sweep's optimum."""
    import consolidate_rq
    b = consolidate_rq.consolidate(_case("spray_dryer")).iloc[0]
    assert b["RQ2_dTmin_opt_K"] != b["RQ2_dTmin_opt_K"] and b["RQ2_dTmin_within_1pct_K"] == ""
