"""External data added for the limitations (0.10.0): frost penalty, retrofit piping, vendor and benchmark checks,
ERSE access tariffs. Known answers are the transcribed source values and hand calculations."""

import json
import math

import pandas as pd
import pytest

from pinch.case import load_case
from pinch.retrofit import piping_cost_EUR
from pinch.sensitivity import apply, parse_sensitivities
from pinch.tariffs import access_tariff_change, with_network_change
from pinch.validation import ROOT

BREWERY = ROOT / "cases" / "brewery.json"


def test_frost_rows_use_the_committed_ambient_shares():
    """The ambient shares stated in the frost rows equal Q_source_external / Q_source of heat_pump_design.csv."""
    design = pd.read_csv(ROOT / "outputs" / "brewery" / "heat_pump_design.csv").set_index("unit")
    share = design["source_external_kWh/hl"] / design["Q_source_kWh/hl"]
    rows = [r for r in json.loads(BREWERY.read_text(encoding="utf-8"))["sensitivities"] if r["kind"] == "frost"]
    assert len(rows) == 2
    for r in rows:
        for unit, s in r["value"]["ambient_share"].items():
            assert s == pytest.approx(share[unit], abs=5e-4), unit


def test_frost_scales_eta_by_the_ambient_share():
    case = load_case(BREWERY)
    row = next(s for s in parse_sensitivities(json.loads(BREWERY.read_text(encoding="utf-8"))["sensitivities"])
               if s.kind == "frost" and s.value["penalty"] == 0.13)
    new = apply(case, row.kind, row.value)
    eta = {lv.name: lv.eta_lorenz or case.eta_lorenz for lv in case.sink_levels}
    eta_new = {lv.name: lv.eta_lorenz for lv in new.sink_levels}
    assert eta_new["Warm-water HP"] == pytest.approx(eta["Warm-water HP"] * (1 - 0.13 * 0.3148))
    assert eta_new["HTHP (wort boiling)"] == pytest.approx(eta["HTHP (wort boiling)"] * 0.87)
    with pytest.raises(ValueError):
        apply(case, "frost", {"penalty": 0.1, "ambient_share": {"No such unit": 1.0}})


def test_piping_cost_hand_calculation():
    """Condensate 101.9 kW over 77 K: m = 0.3166 kg/s, d = 14.2 mm at 2 m/s; 50 m of pipe costs
    105.83 x 50 x 14.2^0.55 NZD / 1.5897 x 797.9/567.5 (Lal et al. 2018, Eq. 2)."""
    cost, d = piping_cost_EUR(101.9, 77.0, 50.0)
    m = 101.9 / (4.18 * 77.0)
    d_hand = 1000 * math.sqrt(4 * m / 1000 / (math.pi * 2.0))
    assert d == pytest.approx(d_hand) and d == pytest.approx(14.20, abs=0.01)
    assert cost == pytest.approx(105.83 * 50 * d_hand ** 0.55 / 1.5897 * 797.9 / 567.5)
    assert piping_cost_EUR(101.9, 77.0, 200.0)[0] == pytest.approx(4 * cost)


def test_piping_appears_in_the_retrofit_equipment():
    eq = pd.read_csv(ROOT / "outputs" / "brewery" / "retrofit_new_equipment.csv")
    pipes = eq[eq["segment"].str.startswith("piping 50 m")]
    expected = piping_cost_EUR(101.9, 77.0, 50.0)[0]        # duty shown rounded to 0.1 kW in the table
    assert len(pipes) >= 1 and ((pipes["cost_EUR"] - expected).abs() < 5).all()


def test_access_tariff_changes_as_published():
    assert access_tariff_change(2027, "MT") == (pytest.approx(-0.135), "proposal")
    assert access_tariff_change(2026, "MT") == (pytest.approx(0.018), "approved")
    assert with_network_change(0.1135, 0.3, -0.135) == pytest.approx(0.1135 * (1 - 0.0405))
    with pytest.raises(ValueError):
        access_tariff_change(2025, "MT")
    with pytest.raises(ValueError):
        with_network_change(0.1, 1.2, -0.1)
