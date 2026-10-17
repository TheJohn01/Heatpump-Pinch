# fourstream_example

Classic four-stream chemical process (two reactor feeds and products), loads in MW. Illustrates the tool on a non-food process with high-temperature demand.

Source: University of Oklahoma, ChE design course notes 'Minimum Utility', Example 1.1 (stream data and targets).

## Energy targets

| Quantity | Value [MW] |
|---|---|
| Total hot / cold stream loads | 61.5 / 59.0 |
| Q̇h,min | 7.5 |
| Q̇c,min | 10.0 |
| Heat recovery | 51.5 |
| Pinch T* [°C] | 145.0 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | HTHP 160 °C, HTHP 200 °C |
| Heat delivered [MW] | 3.75 |
| Electricity [MW] | 0.7941 |
| System COP [-] | 4.722 |
| Residual hot utility [MW] | 3.75 |
| Share of Q̇h,min electrified | 50.0 % |
| External (ambient) source [MW] | 0.0 |

## Annual figures [MWh/year]

Basis: {'type': 'power', 'operating_hours_per_year': 8000}

Q̇h,min 60000.0; Q̇c,min 80000.0; heat pump electricity 6353.0; residual hot utility 30000.0.

## Economics (step 6)

Price ratio 2.551 (electricity 0.1135 EUR/kWh, gas 0.0445 EUR/kWh); boiler efficiency 0.845; 8000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 6,562,500 |
| Full design: annual savings [EUR/year] | 778,369 |
| Full design: simple payback [years] | 8.4311 |
| Full design: NPV [EUR] | -552,141 |
| Full design: CO2 avoided [t/year] | 5,782 |
| Full design: primary-energy reduction | 31.1 % |
| Grass-roots variant (not the RQ1 answer): heat pumps' share of Q̇h,min at target, payback ≤ 5 y | 0.0 % |
| Grass-roots variant: share with maximum NPV | 20.0 % |
| Grass-roots variant: break-even ratio of the full design, NPV = 0 | 2.298 |
| Grass-roots variant: break-even ratio, payback = threshold | 0.661 |

RQ1-RQ3 answers for a site with an existing network (share of today's gas, incremental payback, break-even ratio per unit) are in the retrofit section and in rq_consolidated.md.

### Scenarios (parameter overrides)

| Scenario | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|---|
| with hot-water piping (DEA indirect cost) | 2.551 | 8.29 | -508,476 | 5,782 | 0.0 % | 2.318 |

### Lorenz-efficiency sensitivity (heat pumps re-sized)

| η_L | System COP | Full-design payback [y] | NPV [EUR] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|
| 0.45 | 3.864 | 10.62 | -1,789,438 | 0.0 % | 1.88 |
| 0.52 | 4.465 | 8.91 | -873,362 | 0.0 % | 2.172 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 421.3 EUR/kW-year; cold utility 34.3308 EUR/kW-year; CRF 0.1295/year. Film coefficients: University of Oklahoma ChE design notes 'Units and Area Targeting' (same example): overall U = 0.001 MW/(m2 K) = 1 kW/(m2 K) for every match; split into equal film coefficients of 2 kW/(m2 K) so that 1/U = 1/h_hot + 1/h_cold (lecture notes, not peer-reviewed). Utility-side coefficients take the same value

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| Towler 2020 U-tube shell and tube (carbon steel), bare (F = 1) | 1 (grid edge) | 7,247 | 3,900 | 2,153,236 |
| Towler 2020 U-tube shell and tube (carbon steel) x 3.5 (Hand factor, installed) | 2 | 5,649 | 4,300 | 2,819,261 |

## Plausibility warnings

- **HTHP 200 °C**: sink 200 °C above 160 °C: limited commercial availability

## Provenance

- **stream data**: published (lecture notes, Example 1.1)
- **eta_lorenz**: assumed, same value as the brewery case (Padullés et al., 2026)
- **source_T_C**: assumed: 130 °C, below the pinch (T* 145 °C), where the process rejects heat
- **sink levels**: assumed, illustrative: 160 °C (commercial range) and 200 °C (upper end of IEA HPT Annex 58 scope)
- **basis**: ASSUMED for reproduce_secondary_economics.py: 8000 h/year (case basis_hint). Original: none: the source gives no operating hours
- **ambient_T_C**: assumed: not given by the source
- **economics**: assumed: no economic data in the source (see economics.sources)
- **film coefficients**: from the overall U of the University of Oklahoma notes (equal split)
- **eta_lorenz_sensitivity**: 0.45-0.52: Lorenz (Carnot) efficiencies implied by the DEA catalogue HTHP sheets 2.a/2.b (COP 4.45/2.75/2.4/2.05 at lifts of 40/65/80/100 K), as for the brewery
- **COP check**: eta_lorenz 0.55 (copied from the brewery) is above the 0.45-0.52 implied by the DEA catalogue: COP 7.94 at 30 K lift vs about 5.5-6 extrapolated from DEA (4.45 at 40 K); at 0.45 the NPV10 turns from +0.07 to -1.17 M€
- **steam sink**: assumed: the isothermal sink levels stand for steam mains (conventional for a chemical site; not stated by the source), so the DEA steam add-on applies
