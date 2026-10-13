"""Consolidated RQ1-RQ3 table: base row against the retrofit results and hand checks."""

import pytest

from pinch.validation import ROOT


@pytest.fixture(scope="module")
def table():
    import consolidate_rq
    return consolidate_rq.consolidate(ROOT / "cases" / "brewery_padulles2026.json").set_index("sensitivity")


def test_base_row_matches_retrofit_and_hand_check(table):
    b = table.loc["Base case"]
    # warm-water heat pump increment over the condensate retrofit, from the retrofit table:
    # (1,137,333 - 55,981) EUR / (345,581 - 49,401) EUR/year = 3.65 years
    assert b["warm_water_HP_incremental_payback_y"] == pytest.approx((1_137_333 - 55_981) / (345_581 - 49_401), abs=0.01)
    assert b["RQ3_ratio_warm_water_HP_only"] == pytest.approx(5.011, abs=0.01)
    assert b["RQ3_ratio_full_electrification"] == pytest.approx(2.975, abs=0.01)
    assert b["RQ1_gas_share"] >= 0.735 - 1e-4          # at least the warm-water heat pump option
    assert b["RQ1_payback_y"] <= 5.0 + 1e-9


def test_directions_of_sensitivities(table):
    base = table.loc["Base case", "RQ3_ratio_full_electrification"]
    # more efficient boiler -> less gas saved -> lower break-even ratio
    assert table.loc["Boiler efficiency 1.0 (bound)", "RQ3_ratio_full_electrification"] < base
    # fixed heat pump costs: larger site -> higher break-even ratio
    r = [table.loc[f"Production {x} Mhl/year", "RQ3_ratio_full_electrification"] for x in ("0.25", "0.5")] + \
        [base, table.loc["Production 1.5 Mhl/year", "RQ3_ratio_full_electrification"]]
    assert r == sorted(r)
    # dearer area -> larger optimal dTmin is tested in test_area; here: no credit -> cheaper cold utility -> larger dTmin
    assert table.loc["No refrigeration credit", "RQ2_dTmin_opt_K"] >= table.loc["Base case", "RQ2_dTmin_opt_K"]
