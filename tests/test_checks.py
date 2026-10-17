"""Supervisor-review checks: MVR configuration (B4) and output reproducibility (C2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mvr_check import check, mvr_cop
from regenerate_outputs import STEPS

ROOT = Path(__file__).resolve().parents[1]
BREWERY = ROOT / "cases" / "brewery.json"


@pytest.mark.parametrize("lift_K", [5.0, 10.0, 15.0])
def test_mvr_cop_below_carnot_and_paper_value_inside_range(lift_K: float) -> None:
    """Second law: the MVR COP stays below Carnot for condensing at 100 °C + lift and evaporating at 100 °C."""
    cop, pressure_ratio = mvr_cop(lift_K)
    T_hot_K = 100.0 + lift_K + 273.15
    assert 1.0 < cop < T_hot_K / lift_K
    assert 1.0 < pressure_ratio < 2.0          # single-stage fan territory
    # the paper's COP 15 (Padullés et al. 2026) lies between the 15 K and 20 K lifts
    assert mvr_cop(15.0)[0] > 15.0 > mvr_cop(20.0)[0]


def test_mvr_check_config2_matches_retrofit_increment() -> None:
    """Config. 2 in mvr_check.py must equal the HTHP increment of the retrofit table (same model, F = 1)."""
    df = check(BREWERY)
    row = df[(df["option"].str.startswith("config. 2")) & (df["capacity_factor_F"] == 1.0)].iloc[0]
    inc = pd.read_csv(ROOT / "outputs" / "brewery" / "retrofit_increments.csv")
    hthp = inc[inc["increment"].str.startswith("HTHP")].iloc[0]
    assert row["capex_EUR"] == pytest.approx(hthp["delta_capex_EUR"], rel=1e-6)
    assert row["savings_EUR"] == pytest.approx(hthp["delta_savings_EUR"], abs=2.0)
    assert row["npv_EUR"] == pytest.approx(hthp["delta_npv_EUR"], abs=2.0)
    # config. 3 uses less electricity than config. 2 at every lift but costs more to build
    cfg3 = df[df["option"].str.startswith("config. 3") & (df["capacity_factor_F"] == 1.0)]
    assert (cfg3["electricity_kWh_per_hl"] < row["electricity_kWh_per_hl"]).all()
    assert (cfg3["capex_EUR"] > row["capex_EUR"]).all()


def test_regenerate_outputs_lists_existing_scripts() -> None:
    for step in STEPS:
        assert (ROOT / step[0]).is_file(), step
        for arg in step[1:]:
            assert arg.startswith("--") or (ROOT / arg).is_file(), arg
