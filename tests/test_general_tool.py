"""Tests for the site-independent layer: case files, GCC-based design, screening, CLI.

The design is checked against analytic GCC values of the four-stream example
and against the brewery minimum-energy design obtained step by step.
"""

import json
from pathlib import Path

import pytest

from analyse import analyse
from pinch import load_streams, problem_table
from pinch.case import SinkLevelSpec, load_case, to_MWh_per_year
from pinch.design import design_from_gcc, plausibility_warnings, source_warnings
from pinch.heat_pump import HeatPump
from pinch.validation import ROOT

FOURSTREAM = load_streams(ROOT / "data" / "fourstream_example.csv")


# ---------------------------------------------------------------- design
def test_design_levels_match_gcc_heat_flows():
    """GCC heat flow is 1.5 MW at T* = 160 °C and 3.75 MW at 200 °C (interpolated cascade)."""
    levels = (SinkLevelSpec("A", 160, 160), SinkLevelSpec("B", 200, 200))
    d = design_from_gcc(FOURSTREAM, levels, 0.55, 130)
    duties = {u.name: u.Q_sink for u in d.units}
    assert duties["A"] == pytest.approx(1.5, abs=1e-6)
    assert duties["B"] == pytest.approx(2.25, abs=1e-6)
    assert d.Qh_residual == pytest.approx(7.5 - 3.75, abs=1e-6)
    assert d.fraction_electrified == pytest.approx(0.5, abs=1e-6)


def test_design_order_does_not_matter():
    a = design_from_gcc(FOURSTREAM, (SinkLevelSpec("A", 160, 160), SinkLevelSpec("B", 200, 200)), 0.55, 130)
    b = design_from_gcc(FOURSTREAM, (SinkLevelSpec("B", 200, 200), SinkLevelSpec("A", 160, 160)), 0.55, 130)
    assert a.W_total == pytest.approx(b.W_total)


def test_level_below_pinch_gets_no_duty():
    d = design_from_gcc(FOURSTREAM, (SinkLevelSpec("cold", 100, 100),), 0.55, 50)
    assert d.units == () and d.skipped == ("cold",)
    assert d.Qh_residual == pytest.approx(7.5)


def test_gcc_max_level_electrifies_everything():
    d = design_from_gcc(FOURSTREAM, (SinkLevelSpec("top", "gcc_max", "gcc_max"),), 0.55, 130)
    assert d.fraction_electrified == pytest.approx(1.0, abs=1e-6)


def test_brewery_case_reproduces_step_by_step_design():
    """General tool on the brewery case = minimum-energy design of reproduce_padulles2026.py (3.4404)."""
    case = load_case(ROOT / "cases" / "brewery_padulles2026.json")
    # at the published eta_L 0.55 of Padullés et al. (the case now uses 0.50, an educated approximation)
    d = design_from_gcc(load_streams(case.stream_file), case.sink_levels, 0.55, case.source_T_C)
    assert d.W_total == pytest.approx(3.4404, abs=1e-4)
    assert d.fraction_electrified == pytest.approx(1.0, abs=1e-6)


def test_external_source_is_labelled():
    """Milk evaporator: sources at 15 °C sit above the pinch, so all source heat is ambient."""
    case = load_case(ROOT / "cases" / "walmsley2024_milk_evaporator.json")
    d = design_from_gcc(load_streams(case.stream_file), case.sink_levels, case.eta_lorenz, case.source_T_C)
    assert all(v == "sink above pinch; external source" for v in d.integration.placement.values())
    assert sum(d.integration.Q_source_process.values()) == 0.0


# --------------------------------------------------------------- screening
def test_screening_flags_and_passes():
    ok = HeatPump("ok", 1, 18, 82, -1, -1, eta_lorenz=0.55)
    hot = HeatPump("hot", 1, 210, 210, 150, 150, eta_lorenz=0.55)
    lift = HeatPump("lift", 1, 150, 150, 0, 0, eta_lorenz=0.55)
    assert plausibility_warnings(ok) == []
    assert any("beyond near-term" in w for w in plausibility_warnings(hot))
    assert any("lift" in w for w in plausibility_warnings(lift))


def test_screening_flags_cop_below_one():
    weak = HeatPump("weak", 1, 190, 190, 0, 0, eta_lorenz=0.2)
    assert any("COP" in w for w in plausibility_warnings(weak))


# ------------------------------------------------------------ annual basis
def test_annual_per_product():
    basis = {"type": "per_product", "production_per_year": 1e6, "production_unit": "hl"}
    assert to_MWh_per_year(10.0, "kWh/hl", basis) == pytest.approx(10_000.0)


def test_annual_power():
    basis = {"type": "power", "operating_hours_per_year": 8000}
    assert to_MWh_per_year(7.5, "MW", basis) == pytest.approx(60_000.0)
    assert to_MWh_per_year(500, "kW", basis) == pytest.approx(4_000.0)


def test_annual_rejects_mismatched_units():
    with pytest.raises(ValueError):
        to_MWh_per_year(1.0, "kWh/t", {"type": "per_product", "production_per_year": 1, "production_unit": "hl"})
    with pytest.raises(ValueError):
        to_MWh_per_year(1.0, "kWh/hl", {"type": "power", "operating_hours_per_year": 8000})


def test_no_basis_gives_none():
    assert to_MWh_per_year(1.0, "kW", None) is None


# ------------------------------------------------------------- case files
def test_case_file_validation(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "stream_file": "s.csv", "heat_pumps": {"eta_lorenz": 1.5, "source_T_C": 0}}))
    with pytest.raises(ValueError, match="eta_lorenz"):
        load_case(bad)


def test_template_loads():
    case = load_case(ROOT / "cases" / "TEMPLATE.json")
    assert case.basis["type"] == "power" and len(case.sink_levels) == 2


@pytest.mark.parametrize("case_file", ["brewery_padulles2026.json", "fourstream_example.json",
                                       "walmsley2024_milk_evaporator.json", "walmsley2024_spray_dryer.json"])
def test_cli_writes_all_outputs(case_file, tmp_path: Path):
    summary = analyse(load_case(ROOT / "cases" / case_file), output_root=tmp_path)
    folder = tmp_path / summary["case"]
    for name in ("problem_table.csv", "composite_curves.png", "gcc.png", "gcc_heat_pumps.png",
                 "heat_pump_design.csv", "summary.json", "summary.md"):
        assert (folder / name).exists(), name
    assert summary["targets"]["Qh_min"] == pytest.approx(problem_table(load_streams(
        load_case(ROOT / "cases" / case_file).stream_file)).Qh_min, abs=1e-4)


def test_external_source_above_ambient_is_flagged():
    """Spray dryer with a 35 °C source: the shortfall cannot come from 15 °C ambient air."""
    case = load_case(ROOT / "cases" / "walmsley2024_spray_dryer.json")
    streams = load_streams(case.stream_file)
    hot_source = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, 35.0)
    assert source_warnings(hot_source, case.ambient_T_C)            # flagged
    as_published = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    assert source_warnings(as_published, case.ambient_T_C) == {}    # 15 °C source: fine


def test_every_module_is_documented():
    """The module lists in pinch/__init__.py and README.md name every module (audit 4: the docstring had
    drifted to 4 of 19 modules)."""
    import pinch
    from pinch.validation import ROOT
    modules = sorted(p.stem for p in (ROOT / "pinch").glob("*.py") if p.stem != "__init__")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for m in modules:
        assert f"\n{m} " in pinch.__doc__, f"{m} missing from pinch/__init__.py"
        assert f"  {m}.py " in readme, f"{m} missing from README.md"


def test_problem_table_name_is_unambiguous():
    """Audit 4: `pinch.problem_table` was both a submodule and the function re-exported by __init__."""
    import importlib
    import pinch
    assert callable(pinch.problem_table)
    assert importlib.util.find_spec("pinch.problem_table") is None
    assert importlib.import_module("pinch.problem_table_algorithm").problem_table is pinch.problem_table
