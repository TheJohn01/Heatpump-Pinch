"""Heat pump design check, part load and component cost with TESPy (workflow steps 4b and 6).

``pinch.cycle`` optimises each cycle at one design point. This module rebuilds a single-stage cycle in
TESPy, an independent equation-oriented simulator, to

1. check the design point: same pressures, superheat, subcooling and isentropic efficiency must give the
   same COP (both use CoolProp properties, so this checks the cycle bookkeeping, not the equation of
   state);
2. estimate part-load COP with TESPy's off-design method: heat exchangers keep their design UA scaled by
   TESPy's default characteristic lines, the compressor follows TESPy's default isentropic-efficiency
   line, subcooling stays at its design value, sink temperatures and source flow stay fixed;
3. cost the unit by components (compressor suction volume flow, exchanger areas from UA), the method of
   Kosmadakis, Arpagaus, Neofytou and Bertsch (2020), Energy Conversion and Management 226, 113488, as
   implemented in heatpumps (Freißmann and Fritz, MIT licence, github.com/jfreissmann/heatpumps,
   ``HeatPumpBase.calc_cost``): a second CAPEX estimate next to the Padullés et al. cost function.

Software: TESPy (Francesco Witte and contributors, MIT licence, github.com/oemof/tespy; Witte and
Tuschy 2020, J. Open Source Softw. 5(49), 2178), version pinned in requirements.txt.

Limits (stated in the outputs): TESPy's default characteristic lines are generic, not manufacturer data,
so the part-load curve shows a trend, not a guarantee; it is reported only where TESPy converges without
warnings. The isothermal source of the brewery design (-1 °C) is represented by 30 % (mass) ethylene
glycol from -0.5 to -1.5 °C, so that the evaporator has a counter-current profile (assumption). The
compressor heat loss and motor efficiency of ``pinch.cycle`` are switched off for the comparison (TESPy's
compressor has neither); the cost method needs only flows and UA. Cascades and two-stage cycles are not
rebuilt.
"""

from __future__ import annotations

import logging
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pinch.cycle import CycleAssumptions, CycleResult, SecondaryStream

KOSMADAKIS2020 = ("Kosmadakis et al. (2020), Energy Convers. Manag. 226, 113488, as implemented in "
                  "heatpumps (Freißmann and Fritz, MIT), HeatPumpBase.calc_cost")
#: Chemical Engineering Plant Cost Index values as shipped with heatpumps (models/input/CEPCI.json)
CEPCI = {2013: 567.0, 2019: 608.0, 2020: 596.0, 2021: 708.0, 2022: 813.0, 2023: 798.0}
SOURCE_FLUID = "INCOMP::MEG[0.3]|mass"
SINK_FLUID = "water"


@dataclass(frozen=True)
class TespyDesign:
    COP: float
    COP_pinch_cycle: float
    Q_sink_kW: float
    P_el_kW: float
    UA_evaporator_W_K: float
    UA_condenser_W_K: float
    V_suction_m3_h: float


def _quiet() -> None:
    logging.getLogger("tespy").setLevel(logging.ERROR)


class SingleStageTespy:
    """Simple vapour-compression cycle (no SLHX) with secondary source and sink streams."""

    def __init__(self, fluid: str, source: SecondaryStream, sink: SecondaryStream, cycle: CycleResult,
                 Q_sink_kW: float, assumptions: CycleAssumptions = CycleAssumptions()):
        from tespy.components import Compressor, CycleCloser, HeatExchanger, Sink, Source, Valve
        from tespy.connections import Connection
        from tespy.networks import Network

        _quiet()
        if not cycle.feasible or cycle.transcritical or cycle.layout != "single stage":
            raise ValueError("needs a feasible subcritical single-stage result of pinch.cycle.single_stage")
        self.cycle, self.Q_design = cycle, Q_sink_kW
        nw = Network(iterinfo=False)
        nw.units.set_defaults(temperature="degC", pressure="bar", enthalpy="kJ/kg", heat="kW", power="kW")
        cc, cp, va = CycleCloser("cycle closer"), Compressor("compressor"), Valve("valve")
        ev, co = HeatExchanger("evaporator"), HeatExchanger("condenser")
        so_in, so_out, si_in, si_out = Source("source in"), Sink("source out"), Source("sink in"), Sink("sink out")
        c1 = Connection(cc, "out1", ev, "in2", label="1")
        c2 = Connection(ev, "out2", cp, "in1", label="2")
        c3 = Connection(cp, "out1", co, "in1", label="3")
        c4 = Connection(co, "out1", va, "in1", label="4")
        c5 = Connection(va, "out1", cc, "in1", label="5")
        s1 = Connection(so_in, "out1", ev, "in1", label="s1")
        s2 = Connection(ev, "out1", so_out, "in1", label="s2")
        w1 = Connection(si_in, "out1", co, "in2", label="w1")
        w2 = Connection(co, "out2", si_out, "in1", label="w2")
        nw.add_conns(c1, c2, c3, c4, c5, s1, s2, w1, w2)

        T_src = (source.T_in_C + source.T_out_C) / 2
        src_in, src_out = (T_src + 0.5, T_src - 0.5) if source.T_in_C == source.T_out_C else \
            (source.T_in_C, source.T_out_C)
        T4 = min(sink.T_in_C + assumptions.dT_pinch_sink_K, cycle.T_cond_C)
        cp.set_attr(eta_s=assumptions.eta_is_compressor, design=["eta_s"], offdesign=["eta_s_char"])
        ev.set_attr(pr1=1, pr2=1, offdesign=["UA_char"])
        co.set_attr(pr1=1, pr2=1, Q=-Q_sink_kW, offdesign=["UA_char"])
        c2.set_attr(p=cycle.P_low_bar, td_dew=assumptions.dT_superheat_K, fluid={fluid: 1}, design=["p"])
        c3.set_attr(p=cycle.P_high_bar, design=["p"])
        c4.set_attr(T=T4, design=["T"], offdesign=["td_bubble"])
        s1.set_attr(T=src_in, p=2.0, fluid={SOURCE_FLUID: 1}, offdesign=["m"])
        s2.set_attr(T=src_out, design=["T"])
        w1.set_attr(T=sink.T_in_C, p=5.0, fluid={SINK_FLUID: 1})
        w2.set_attr(T=sink.T_out_C)
        self.nw, self.cp, self.ev, self.co, self.c2 = nw, cp, ev, co, c2
        self._dir = tempfile.TemporaryDirectory()
        self.design_path = str(Path(self._dir.name) / "design")

    def design(self, COP_pinch_cycle: float) -> TespyDesign:
        self.nw.solve("design")
        self.nw.save(self.design_path)
        Q = abs(self.co.Q.val)
        return TespyDesign(Q / self.cp.P.val, COP_pinch_cycle, Q, self.cp.P.val, self.ev.UA.val, self.co.UA.val,
                           self.c2.v.val * 3600)

    def part_load(self, fraction: float) -> tuple[float, float, bool]:
        """(COP, compressor isentropic efficiency, converged without warnings) at a fraction of design heat."""
        self.co.set_attr(Q=-self.Q_design * fraction)
        self.nw.solve("offdesign", design_path=self.design_path)
        ok = getattr(self.nw, "status", 0) == 0
        return abs(self.co.Q.val) / self.cp.P.val, self.cp.eta_s.val, ok


@dataclass(frozen=True)
class ComponentCost:
    compressor: float
    evaporator: float
    condenser: float
    equipment: float               # with piping and tanks, electrical equipment and refrigerant
    total_capital: float           # equipment x 6.32
    year: int


def kosmadakis_cost(V_suction_m3_h: float, UA_evaporator_W_K: float, UA_condenser_W_K: float,
                    year: int = 2023, k_evaporator_W_m2K: float = 1500.0,
                    k_condenser_W_m2K: float = 3500.0) -> ComponentCost:
    """Component cost (€ of ``year``) following heatpumps' ``calc_cost`` (reference year 2013, CEPCI).

    C = C_ref (X / X_ref)^α: compressor X = suction volume flow [m³/h] (279.8, 19 850 €, 0.73); heat
    exchangers X = area UA / k [m²] (42, 15 526 €, 0.80); piping and tanks 10 % and electrical equipment
    10 % of the components; refrigerant (1.2 Σ) (1/0.96 - 1); total capital = 6.32 x equipment.
    """
    f = CEPCI[year] / CEPCI[2013]

    def law(x: float, x_ref: float, c_ref: float, a: float) -> float:
        return c_ref * (x / x_ref) ** a * f

    comp = law(V_suction_m3_h, 279.8, 19850.0, 0.73)
    evap = law(UA_evaporator_W_K / k_evaporator_W_m2K, 42.0, 15526.0, 0.80)
    cond = law(UA_condenser_W_K / k_condenser_W_m2K, 42.0, 15526.0, 0.80)
    s = comp + evap + cond
    equipment = s + 0.1 * s + 0.1 * s + 1.2 * s * (1 / 0.96 - 1)
    return ComponentCost(comp, evap, cond, equipment, 6.32 * equipment, year)


def nan_if_failed(x: float, ok: bool) -> float:
    return x if ok else math.nan
