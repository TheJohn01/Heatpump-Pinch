# walmsley2024_milk_evaporator

Two-effect MVR milk evaporator with milk heat treatment, 247 t/h raw milk (30 t/h milk powder); evaporation system in isolation. Loads in kW.

Source: Walmsley, Lincoln, Padullés, Cleland (2024), Energies 17, 2838, Table 2.

## Energy targets

| Quantity | Value [kW] |
|---|---|
| Total hot / cold stream loads | 21163.5 / 24249.7 |
| Q̇h,min | 3542.2 |
| Q̇c,min | 456.0 |
| Heat recovery | 20707.5 |
| Pinch T* [°C] | 10.5, 7.5 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | HP warm (milk preheat), HTHP 105 °C |
| Heat delivered [kW] | 3542.2 |
| Electricity [kW] | 1461.7724 |
| System COP [-] | 2.423 |
| Residual hot utility [kW] | 0.0 |
| Share of Q̇h,min electrified | 100.0 % |
| External (ambient) source [kW] | 2080.4276 |

## Annual figures [MWh/year]

Basis: {'type': 'power', 'operating_hours_per_year': 8000}

Q̇h,min 28337.6; Q̇c,min 3648.0; heat pump electricity 11694.2; residual hot utility 0.0.

## Economics (step 6)

Price ratio 2.136 (electricity 0.0897 EUR/kWh, gas 0.042 EUR/kWh); boiler efficiency 0.845; 8000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 5,104,568 |
| Full design: annual savings [EUR/year] | 286,496 |
| Full design: simple payback [years] | 17.8172 |
| Full design: NPV [EUR] | -2,892,318 |
| Full design: CO2 avoided [t/year] | 4,852 |
| Full design: primary-energy reduction | 25.3 % |
| Grass-roots variant (not the RQ1 answer): heat pumps' share of Q̇h,min at target, payback ≤ 5 y | 24.5 % |
| Grass-roots variant: share with maximum NPV | 18.0 % |
| Grass-roots variant: break-even ratio of the full design, NPV = 0 | 1.373 |
| Grass-roots variant: break-even ratio, payback = threshold | 0.64 |

RQ1-RQ3 answers for a site with an existing network (share of today's gas, incremental payback, break-even ratio per unit) are in the retrofit section and in rq_consolidated.md.

### Scenarios (parameter overrides)

| Scenario | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|---|
| with hot-water piping (DEA indirect cost) | 2.136 | 14.94 | -2,848,227 | 4,852 | 23.5 % | 1.385 |

### Lorenz-efficiency sensitivity (heat pumps re-sized)

| η_L | System COP | Full-design payback [y] | NPV [EUR] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|
| 0.45 | 2.181 | 30.04 | -3,792,302 | 23.0 % | 1.236 |
| 0.52 | 2.52 | 15.62 | -2,580,785 | 25.0 % | 1.428 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 397.63 EUR/kW-year; cold utility 136.16698292220116 EUR/kW-year; CRF 0.1295/year. Film coefficients: Stampfli et al. (2018), CET 70, 901-906, Table 1 (dairy plant): liquid product 500, water 2,000, evaporation/condensation 5,000 W/(m2 K). Mapping to these streams is our assumption: water for chiller water, CIP, direct-use water and cow water (milk condensate); product for raw milk and concentrate; condensation for vapour bleed, condenser and flash vapours

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| Towler 2020 plate and frame (304 SS), bare (F = 1) | 5 | 4,699 | 3,542 | 1,591,962 |
| Towler 2020 plate and frame (304 SS) x 3.5 (Hand factor, installed) | 5 | 4,699 | 3,542 | 1,895,395 |

## Provenance

- **stream data**: published (Table 2); Table 2 dT_cont used (chiller water 0.5 K; the text's pinch range implies 2.5 K, which leaves the targets unchanged)
- **eta_lorenz**: published: 50 % exergetic (Carnot) efficiency (Sec. 4.2); reproduces the paper's simple-design COP 2.1
- **source_T_C**: published: ambient / dead state 15 °C (Sec. 2), the source of the paper's simple design
- **sink levels**: 105 °C published (simple design, Sec. 4.2.3); the 15-55 °C level is assumed (illustrative, follows the low-temperature part of the GCC)
- **basis**: ASSUMED for reproduce_secondary_economics.py: 8000 h/year (case basis_hint). Original: none: operating hours not given
- **ambient_T_C**: published: dead state 15 °C (Sec. 2)
- **economics**: assumed: no economic data in the source (see economics.sources)
- **film coefficients**: Stampfli et al. (2018) dairy values, stream mapping assumed
- **eta_lorenz_sensitivity**: 0.45-0.52: Lorenz (Carnot) efficiencies implied by the DEA catalogue HTHP sheets 2.a/2.b (COP 4.45/2.75/2.4/2.05 at lifts of 40/65/80/100 K), as for the brewery
- **COP check**: HTHP 105 °C (steam, 90 K lift): COP 2.10 vs DEA sheet 2.a 2.22 at 90 K minus 0.15 for steam = 2.07 (+1.5 %). Warm-water heat pump 15 -> 55 °C: Lorenz COP 7.86 vs DEA sheet 1.1 'up to 60 °C, lift 40 K' 5.33 (+47 %; the Lorenz model credits the full 40 K sink glide, which needs a glide-matched cycle such as transcritical CO2); with COP 5.33 RQ1 falls from 26 % to 23 %
- **steam sink**: verified: the 105 °C level supplies the Direct Steam Injection that follows the 8 -> 95 °C preheat (Walmsley et al. 2024, Sec. 3.2), so the DEA steam-generation add-on applies
