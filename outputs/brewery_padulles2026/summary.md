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
| Full design: annual savings [EUR/year] | 273,220 |
| Full design: simple payback [years] | 6.5631 |
| Full design: NPV [EUR] | 316,554 |
| Full design: CO2 avoided [t/year] | 1,872 |
| Full design: primary-energy reduction | 50.7 % |
| RQ1: largest share of Q̇h,min with payback ≤ 5 y | 72.5 % |
| RQ1: share with maximum NPV | 72.5 % |
| RQ3: break-even ratio, NPV = 0 | 2.512 |
| RQ3: break-even ratio, payback = threshold | 1.603 |

### Scenarios (parameter overrides)

| Scenario | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|---|
| Prices 2025-S2 (ID 0.1216 / I3 0.0481) | 2.528 | 8.36 | -137,840 | 1,872 | 72.5 % | 2.391 |
| Prices 2025-S1 (ID 0.1230 / I3 0.0546) | 2.253 | 6.23 | 429,287 | 1,872 | 72.5 % | 2.628 |
| Electricity band IE (0.0897), 2026-S1 | 1.752 | 5.31 | 815,801 | 1,872 | 72.5 % | 2.512 |
| Previous inputs (ECO-reported 2025-S1: 0.132 / 0.055) | 2.4 | 6.69 | 277,204 | 1,872 | 72.5 % | 2.64 |
| Boiler efficiency 0.817 (US DOE) | 2.217 | 6.1 | 477,581 | 1,946 | 72.5 % | 2.661 |
| Boiler efficiency 0.929 (implied by Padulles App. B, DK1) | 2.217 | 8.22 | -108,288 | 1,677 | 72.5 % | 2.116 |
| Boiler efficiency 1.0 (bound) | 2.217 | 10.02 | -411,721 | 1,537 | 0.0 % | 1.833 |
| EU ETS CO2 price 82.4 EUR/t | 2.217 | 3.97 | 1,692,788 | 1,872 | 100.0 % | 3.793 |
| Gas EF 0.219 (Padulles Sec. 5.3) | 2.217 | 6.56 | 316,554 | 2,312 | 72.5 % | 2.512 |
| Grid EF 0.092 (APA mainland 2023) | 2.217 | 6.56 | 316,554 | 1,913 | 72.5 % | 2.512 |
| Grid EF 0.167 (APA 5-year average 2019-2023) | 2.217 | 6.56 | 316,554 | 1,709 | 72.5 % | 2.512 |
| Grid EF 0.1172 (Electricity Maps 2025) | 2.217 | 6.56 | 316,554 | 1,845 | 72.5 % | 2.512 |
| No refrigeration credit (as Padulles et al. 2026) | 2.217 | 9.39 | -317,849 | 1,795 | 0.0 % | 1.983 |
| Chiller COP 6.68 (0.9 x Carnot, Towler upper bound) | 2.217 | 7.3 | 104,770 | 1,846 | 72.5 % | 2.306 |
| Refrigeration credit 50 % (batch mismatch) | 2.217 | 7.72 | -648 | 1,834 | 72.5 % | 2.216 |

## Retrofit of the existing network (step 5)

Existing network 'N0 existing': Q̇h 11.3 (target 10.0424), energy gap 1.2577 = cross-pinch in matches 0.0 + heaters below the pinch 0.0 + coolers above the pinch 1.2576; refrigeration below ambient 3.2212.

| Option | Q̇h network | Heat pumps | CAPEX [EUR] | Payback [y] | NPV [EUR] | Gas reduction vs existing |
|---|---|---|---|---|---|---|
| N1: condensate into tank | 10.4847 | none | 55,972 | 1.11 | 333,235 | 7.2 % |
| N0 + both heat pumps (Padulles config. 2) | 11.3 | CO2 HP (warm water) 8.30 (COP 3.55), HTHP (wort boiling) 3.00 (COP 1.99) | 1,887,500 | 6.3 | 427,439 | 100.0 % |
| N1 + both heat pumps | 10.4847 | CO2 HP (warm water) 7.48 (COP 3.55), HTHP (wort boiling) 3.00 (COP 1.99) | 1,882,325 | 5.72 | 658,678 | 100.0 % |
| N1 + warm-water heat pump only | 10.4847 | CO2 HP (warm water) 7.48 (COP 3.55) | 1,137,325 | 3.48 | 1,383,908 | 73.5 % |
| N1 + both heat pumps, cycle-based COP | 10.4847 | CO2 HP (warm water) 7.48 (COP 3.11), HTHP (wort boiling) 3.00 (COP 1.96) | 1,882,325 | 6.44 | 375,737 | 100.0 % |

## Cycle-based design (step 4b: η_L from the working-fluid cycle model)

| Unit | Fluid | Layout | COP | η_L |
|---|---|---|---|---|
| CO2 HP (warm water) | n-Propane | single stage, SLHX | 3.109 | 0.4821 |
| HTHP (wort boiling) | n-Propane / n-Butane | cascade (SLHX top) | 1.956 | 0.5408 |

System COP 2.676; full-design payback 7.54 y, NPV 42,454 EUR; RQ1 72.5 %; RQ3 break-even ratio 2.252.

### Lorenz-efficiency sensitivity (heat pumps re-sized)

| η_L | System COP | Full-design payback [y] | NPV [EUR] | RQ1 | RQ3 (NPV = 0) |
|---|---|---|---|---|---|
| 0.45 | 2.388 | 9.62 | -353,505 | 72.5 % | 1.96 |
| 0.52 | 2.76 | 7.15 | 142,596 | 72.5 % | 2.341 |
| 0.63 | 3.343 | 5.55 | 699,445 | 72.5 % | 2.993 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 484.73 EUR/kW-year; cold utility 204.04494382022472 EUR/kW-year; CRF 0.1295/year. Film coefficients: Stampfli et al. (2018), CET 70, 901-906, Table 1 (dairy streams): product 500, water 2,000, evaporation/condensation 5,000 W/(m2 K); checked against the PDF. Mapping to brewery streams is our assumption: water for brewing-water, CIP and condensate; product for mash, wort and beer; latent for boiling and boil-off condensation.

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| Towler 2020 plate & frame, bare (F = 1) | 0.2 | 335 | 1,203 | 672,712 |
| Towler 2020 x 3.5 (Hand factor, installed) | 0.6 | 270 | 1,208 | 701,795 |
| Stampfli 2018 (cross-check only), bare (F = 1) | 0.5 | 281 | 1,207 | 690,145 |
| Stampfli 2018 (cross-check only) x 3.5 (Hand factor) | 1.6 | 211 | 1,222 | 750,288 |
| sweep: 100 EUR/m2 installed, linear (not a sourced estimate) | 0.08 | 390 | 1,201 | 664,008 |
| sweep: 250 EUR/m2 installed, linear (not a sourced estimate) | 0.2 | 335 | 1,203 | 670,954 |
| sweep: 500 EUR/m2 installed, linear (not a sourced estimate) | 0.4 | 294 | 1,206 | 681,034 |
| sweep: 1000 EUR/m2 installed, linear (not a sourced estimate) | 0.8 | 253 | 1,211 | 698,524 |
| sweep: 2000 EUR/m2 installed, linear (not a sourced estimate) | 1.6 | 211 | 1,222 | 728,182 |

## Provenance

- **stream data**: published (Table 2); 'Amb.' taken as 15 °C (Sec. 4.3.1), an inference
- **eta_lorenz**: published (Sec. 4.3.1, citing Andersen et al.); sensitivity 0.45, 0.52, 0.63 (see economics.sources)
- **source_T_C**: published cold-utility temperature (Sec. 4.1); used for all sources, which bounds W from above
- **sink levels**: published warm-water tank 18-82 °C (Fig. 14); HTHP at GCC maximum T* (assumed, consistent with COP 2)
- **basis**: assumed: 1.0 million hl/year, within the published range of Table 1 (0.25-1.5 million hl/year); economics at 8000 h/year (published)
- **ambient_T_C**: published: Sec. 4.3.1
- **area_targeting**: film coefficients: Stampfli et al. (2018) Table 1, mapping assumed; cost laws: Sinnott and Towler (2020) Table 6.6 plate and frame (primary) and Stampfli et al. (2018) Table 2, bare and x3.5 (Hand factor, Towler Table 6.3); cold utility cost from chiller COP
- **cycle_screening**: step 4b: cycle model with Andersen et al. (2024) Table 3 assumptions; validated against their Appendix A (see tests/test_cycle.py)
- **retrofit**: step 5, option (a): existing network = Padullés et al. (2026) Sec. 4.2 (Pfaduko + wort-cooling HR tank), data/brewery_networks.json
