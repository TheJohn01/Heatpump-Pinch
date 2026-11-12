"""TESPy rebuild of single-stage cycles (pinch.tespy_heat_pump): design point equals pinch.cycle, part-load
trend, and the component cost method of Kosmadakis et al. (2020) as implemented in heatpumps."""

import pandas as pd
import pytest

pytest.importorskip("tespy")

from pinch.cycle import CycleAssumptions, SecondaryStream, single_stage
from pinch.tespy_heat_pump import CEPCI, SingleStageTespy, kosmadakis_cost

SAME = CycleAssumptions(heat_loss_factor=0.0, eta_motor=1.0)
SOURCE, SINK = SecondaryStream(-1.0, -1.0), SecondaryStream(18.0, 82.0)    # brewery warm-water unit


@pytest.mark.parametrize("fluid", ["n-Propane", "IsoButane"])
def test_tespy_reproduces_the_design_cop(fluid):
    r = single_stage(fluid, SOURCE, SINK, SAME)
    d = SingleStageTespy(fluid, SOURCE, SINK, r, 500.0, SAME).design(r.COP)
    assert d.COP == pytest.approx(r.COP, rel=2e-4)
    assert d.Q_sink_kW == pytest.approx(500.0)
    assert d.P_el_kW == pytest.approx(500.0 / r.COP, rel=2e-4)


def test_part_load_trend():
    r = single_stage("n-Propane", SOURCE, SINK, SAME)
    m = SingleStageTespy("n-Propane", SOURCE, SINK, r, 500.0, SAME)
    m.design(r.COP)
    cops = []
    for f in (1.0, 0.8, 0.6):
        cop, eta_s, ok = m.part_load(f)
        assert ok
        cops.append(cop)
    assert cops[0] == pytest.approx(r.COP, rel=2e-4)
    assert cops[0] >= cops[1] >= cops[2] > 0.8 * cops[0]       # efficiency falls with load, within reason


def test_rejects_cycles_it_cannot_rebuild():
    r = single_stage("n-Propane", SOURCE, SINK, SAME, slhx=True)
    with pytest.raises(ValueError, match="single-stage"):
        SingleStageTespy("n-Propane", SOURCE, SINK, r, 500.0, SAME)


def test_component_cost_hand_calculation():
    """At the reference sizes in the reference year every component costs C_ref: 19 850 + 2 x 15 526 €;
    equipment = Σ (1 + 0.1 + 0.1 + 1.2 (1/0.96 - 1)) = 1.25 Σ; total = 6.32 x equipment."""
    c = kosmadakis_cost(279.8, 42 * 1500.0, 42 * 3500.0, year=2013)
    s = 19850.0 + 2 * 15526.0
    assert (c.compressor, c.evaporator, c.condenser) == pytest.approx((19850.0, 15526.0, 15526.0))
    assert c.equipment == pytest.approx(1.25 * s)
    assert c.total_capital == pytest.approx(6.32 * 1.25 * s)
    assert kosmadakis_cost(279.8, 42 * 1500.0, 42 * 3500.0, 2023).total_capital == pytest.approx(
        c.total_capital * CEPCI[2023] / CEPCI[2013])


def test_committed_check():
    load = pd.read_csv("outputs/brewery/heat_pump_partload.csv")
    d = load[(load["unit"] == "Warm-water HP") & (load["load_fraction"] == 1.0)].iloc[0]
    assert d["COP_tespy"] == pytest.approx(d["COP_pinch_cycle"], abs=2e-4)
    cost = pd.read_csv("outputs/brewery/heat_pump_cost_check.csv")
    assert 0.5 < cost["ratio_total_to_case"].iloc[0] < 2.0
