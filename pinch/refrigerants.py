"""Working-fluid screening against the EU F-gas Regulation (workflow step 4b).

Regulation (EU) 2024/573 on fluorinated greenhouse gases (in force 11 March 2024) prohibits placing on the
market stationary heat pumps that contain fluorinated greenhouse gases above a GWP limit, by equipment
type, capacity and date (Article 11, Annex IV). The prohibitions concern fluorinated gases only:
hydrocarbons, ammonia, CO2 and water are outside them, whatever their GWP.

Source used (official, read 2026-11-11): European Commission, DG Climate Action, "Stationary air
conditioning and heat pumps" (climate-friendly alternatives to F-gases),
https://climate.ec.europa.eu/eu-action/fluorinated-greenhouse-gases/climate-friendly-alternatives-f-gases/air-conditioning_en.
The page restates Annex IV and gives GWP100 from Annexes I and II of the Regulation (non-fluorinated
substances under Annex VI) with ASHRAE safety groups. The Regulation's own text (EUR-Lex) could not be
fetched in this session; check Annex IV there before citing a date.

Annex IV as stated on that page, for the equipment a process heat pump can be
---------------------------------------------------------------------------------
* Monoblock and other self-contained heat pumps > 12 kW and <= 50 kW: GWP >= 150 prohibited from 1 Jan 2027.
* Other self-contained heat pumps (no capacity limit): GWP >= 150 prohibited from 1 Jan 2030.
* Split systems > 12 kW: GWP >= 750 prohibited from 1 Jan 2029; GWP >= 150 from 1 Jan 2033.
* Each with the exception "except where required to meet safety requirements" (limit then 750).
Industrial heat pumps of the brewery's size (MW) are "other self-contained" equipment.

Not covered here: EN 378 charge limits and machinery-room rules for flammable (A3) and toxic (B2L)
fluids. EN 378:2016 was not available to us; the safety group is reported so the user can apply it.
"""

from __future__ import annotations

from dataclasses import dataclass

EC_PAGE = ("European Commission, DG Climate Action, 'Stationary air conditioning and heat pumps' (GWP100 from "
           "Regulation (EU) 2024/573 Annexes I-II, non-fluorinated under Annex VI), read 2026-11-11")


@dataclass(frozen=True)
class Refrigerant:
    coolprop_name: str
    designation: str
    fluorinated: bool                  # within the scope of the F-gas Regulation's prohibitions
    gwp100: float | None               # None: not given in the source used
    safety_group: str | None           # ASHRAE 34 class as listed on the EC page; None: not listed there
    note: str = ""


#: Fluids screened by the repository's cycle model. GWP and safety group only where the EC page gives them.
REFRIGERANTS: dict[str, Refrigerant] = {r.coolprop_name: r for r in (
    Refrigerant("Ammonia", "R-717", False, 0.0, "B2L"),
    Refrigerant("CarbonDioxide", "R-744", False, 1.0, "A1"),
    Refrigerant("n-Propane", "R-290", False, 0.02, "A3"),
    Refrigerant("Propylene", "R-1270", False, 0.0, "A3",
                "the EC page lists R-1270 twice (propene A3, propylene A4); A3 taken"),
    Refrigerant("R1233zd(E)", "R-1233zd(E)", True, 3.88, "A1"),
    Refrigerant("R1234ze(E)", "R-1234ze(E)", True, 1.37, "A2L"),
    Refrigerant("R1336mzz(Z)", "R-1336mzz(Z)", True, 2.08, "A1"),
    Refrigerant("n-Butane", "R-600", False, None, None, "hydrocarbon: not an F-gas; GWP not on the EC page"),
    Refrigerant("IsoButane", "R-600a", False, None, None, "hydrocarbon: not an F-gas; GWP not on the EC page"),
    Refrigerant("n-Pentane", "R-601", False, None, None, "hydrocarbon: not an F-gas; GWP not on the EC page"),
    Refrigerant("DimethylEther", "R-E170", False, None, None, "ether: not an F-gas; GWP not on the EC page"),
    Refrigerant("Water", "R-718", False, 0.0, "A1"),
)}

#: (equipment, min capacity kW exclusive, max capacity kW inclusive or None, GWP limit, prohibited from year)
ANNEX_IV_RULES: tuple[tuple[str, float, float | None, float, int], ...] = (
    ("self-contained", 12.0, 50.0, 150.0, 2027),
    ("self-contained", 50.0, None, 150.0, 2030),
    ("split", 12.0, None, 750.0, 2029),
    ("split", 12.0, None, 150.0, 2033),
)


def lookup(fluid: str) -> Refrigerant | None:
    """The refrigerant record of a CoolProp name; None if not in the table."""
    return REFRIGERANTS.get(fluid)


def fgas_issues(fluid: str, capacity_kW: float, year: int, equipment: str = "self-contained") -> list[str]:
    """Annex IV prohibitions that would apply to a new heat pump with this fluid (empty: none).

    ``fluid`` may be a cascade "bottom / top". A fluid missing from the table is reported, not passed.
    The "except where required to meet safety requirements" clause is not evaluated.
    """
    if equipment not in ("self-contained", "split"):
        raise ValueError("equipment must be 'self-contained' or 'split'")
    if capacity_kW <= 0:
        raise ValueError("capacity_kW must be positive")
    out = []
    for name in (f.strip() for f in fluid.split("/")):
        r = lookup(name)
        if r is None:
            out.append(f"{name}: not in the refrigerant table, F-gas status unknown")
            continue
        if not r.fluorinated:
            continue
        if r.gwp100 is None:
            out.append(f"{name}: fluorinated, GWP unknown")
            continue
        for eq, lo, hi, limit, since in ANNEX_IV_RULES:
            if eq == equipment and capacity_kW > lo and (hi is None or capacity_kW <= hi) \
                    and r.gwp100 >= limit and year >= since:
                out.append(f"{r.designation}: GWP {r.gwp100:g} >= {limit:g}, prohibited for new {equipment} "
                           f"heat pumps from {since} (Reg. (EU) 2024/573, Annex IV)")
    return out
