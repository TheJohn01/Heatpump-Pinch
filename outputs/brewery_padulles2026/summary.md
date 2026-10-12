# brewery_padulles2026

Generalized reference brewery: 12 process streams, loads per hectolitre of beer.

Source: Padullés et al. (2026), Energy Conversion and Management 357, 121292, Table 2.

## Energy targets

| Quantity | Value [kWh/hl] |
|---|---|
| Total hot / cold stream loads | 14.8 / 21.4 |
| Q̇h,min | 10.0424 |
| Q̇c,min | 3.4424 |
| Heat recovery | 11.3576 |
| Pinch T* [°C] | 17.0 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | CO2 HP (warm water), HTHP (wort boiling) |
| Heat delivered [kWh/hl] | 10.0424 |
| Electricity [kWh/hl] | 3.4404 |
| System COP [-] | 2.919 |
| Residual hot utility [kWh/hl] | 0.0 |
| Share of Q̇h,min electrified | 100.0 % |
| External (ambient) source [kWh/hl] | 3.1596 |

## Annual figures [MWh/year]

Basis: {'type': 'per_product', 'production_per_year': 1000000.0, 'production_unit': 'hl'}

Q̇h,min 10042.4; Q̇c,min 3442.4; heat pump electricity 3440.4; residual hot utility 0.0.

## Economics (step 6)

Price ratio 2.217 (electricity 0.1135 EUR/kWh, gas 0.0512 EUR/kWh); boiler efficiency 0.845; 8000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 1,793,176 |
| Full design: annual savings [EUR/year] | 217,993 |
| Full design: simple payback [years] | 8.2259 |
| Full design: NPV [EUR] | -109,895 |
| Full design: CO2 avoided [t/year] | 1,795 |
| Full design: primary-energy reduction | 45.0 % |
| RQ1: largest share of Q̇h,min with payback ≤ 5 y | 0.0 % |
| RQ1: share with maximum NPV | 72.5 % |
| RQ3: break-even ratio, NPV = 0 | 2.136 |
| RQ3: break-even ratio, payback = threshold | 1.418 |

### Scenarios (parameter overrides)

| Scenario | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|---|
| Prices 2025-S2 (ID 0.1216 / I3 0.0481) | 2.528 | 11.7 | -609,563 | 1,795 | 0.0 % | 2.051 |
| Prices 2025-S1 (ID 0.1230 / I3 0.0546) | 2.253 | 7.94 | -50,261 | 1,795 | 72.5 % | 2.218 |
| Electricity band IE (0.0897), 2026-S1 | 1.752 | 5.98 | 522,381 | 1,795 | 72.5 % | 2.136 |
| Previous inputs (ECO-reported 2025-S1: 0.132 / 0.055) | 2.4 | 8.99 | -252,649 | 1,795 | 0.0 % | 2.227 |
| Boiler efficiency 0.817 (US DOE) | 2.217 | 7.51 | 51,133 | 1,869 | 72.5 % | 2.254 |
| Boiler efficiency 0.929 (implied by Padulles App. B, DK1) | 2.217 | 11.0 | -534,736 | 1,599 | 0.0 % | 1.824 |
| Boiler efficiency 1.0 (bound) | 2.217 | 14.5 | -838,169 | 1,460 | 0.0 % | 1.601 |
| EU ETS CO2 price 82.4 EUR/t | 2.217 | 4.53 | 1,266,339 | 1,795 | 100.0 % | 3.148 |
| Gas EF 0.219 (Padulles Sec. 5.3) | 2.217 | 8.23 | -109,895 | 2,235 | 0.0 % | 2.136 |
| Grid EF 0.092 (APA mainland 2023) | 2.217 | 8.23 | -109,895 | 1,846 | 0.0 % | 2.136 |
| Grid EF 0.167 (APA 5-year average 2019-2023) | 2.217 | 8.23 | -109,895 | 1,588 | 0.0 % | 2.136 |
| Grid EF 0.1172 (Electricity Maps 2025) | 2.217 | 8.23 | -109,895 | 1,760 | 0.0 % | 2.136 |

### Lorenz-efficiency sensitivity (heat pumps re-sized)

| η_L | System COP | Full-design payback [y] | NPV [EUR] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|
| 0.45 | 2.388 | 13.67 | -779,954 | 0.0 % | 1.748 |
| 0.52 | 2.76 | 9.17 | -283,852 | 0.0 % | 2.019 |
| 0.63 | 3.343 | 6.7 | 272,996 | 72.5 % | 2.447 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 484.73 EUR/kW-year; cold utility 0.0 EUR/kW-year; CRF 0.1295/year. Film coefficients: Stampfli et al. (2018), CET 70, 901-906, Table 1 (dairy streams): product 500, water 2,000, evaporation/condensation 5,000 W/(m2 K); checked against the PDF. Mapping to brewery streams is our assumption: water for brewing-water, CIP and condensate; product for mash, wort and beer; latent for boiling and boil-off condensation.

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| Stampfli 2018, bare (F = 1) | 0.7 | 260 | 1,210 | 612,043 |
| Stampfli 2018 x 3.5 (Hand factor) | 2.5 | 185 | 1,235 | 668,296 |
| sweep: 100 EUR/m2 installed, linear (not a sourced estimate) | 0.1 | 377 | 1,201 | 587,227 |
| sweep: 250 EUR/m2 installed, linear (not a sourced estimate) | 0.3 | 311 | 1,204 | 593,760 |
| sweep: 500 EUR/m2 installed, linear (not a sourced estimate) | 0.6 | 270 | 1,208 | 603,165 |
| sweep: 1000 EUR/m2 installed, linear (not a sourced estimate) | 1.1 | 234 | 1,215 | 619,308 |
| sweep: 2000 EUR/m2 installed, linear (not a sourced estimate) | 2.5 | 185 | 1,235 | 646,337 |

## Provenance

- **stream data**: published (Table 2); 'Amb.' taken as 15 °C (Sec. 4.3.1), an inference
- **eta_lorenz**: published (Sec. 4.3.1, citing Andersen et al.); sensitivity 0.45, 0.52, 0.63 (see economics.sources)
- **source_T_C**: published cold-utility temperature (Sec. 4.1); used for all sources, which bounds W from above
- **sink levels**: published warm-water tank 18-82 °C (Fig. 14); HTHP at GCC maximum T* (assumed, consistent with COP 2)
- **basis**: assumed: 1.0 million hl/year, within the published range of Table 1 (0.25-1.5 million hl/year); economics at 8000 h/year (published)
- **ambient_T_C**: published: Sec. 4.3.1
- **area_targeting**: film coefficients: Stampfli et al. (2018) Table 1 (checked), mapping assumed; cost law: Stampfli et al. (2018) Table 2, converted to EUR 2023; installed cost bracketed by F = 1 and F = 3.5 (assumed)
