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

Price ratio 2.4 (electricity 0.132 EUR/kWh, gas 0.055 EUR/kWh); boiler efficiency 0.817; 8000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 1,793,176 |
| Full design: annual savings [EUR/year] | 221,907 |
| Full design: simple payback [years] | 8.0808 |
| Full design: NPV [EUR] | -79,671 |
| Full design: CO2 avoided [t/year] | 2,289 |
| Full design: primary-energy reduction | 46.8 % |
| RQ1: largest share of Q̇h,min with payback ≤ 5 y | 72.5 % |
| RQ1: share with maximum NPV | 72.5 % |
| RQ3: break-even ratio, NPV = 0 | 2.345 |
| RQ3: break-even ratio, payback = threshold | 1.677 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 538.56 EUR/kW-year; cold utility 0.0 EUR/kW-year; CRF 0.1295/year. Film coefficients: categories from Stampfli et al. (2018), CET 70, Table 1 (dairy): product 0.5, water 2.0, evaporation/condensation 5.0 kW/(m2 K) (values read via web transcription; to be checked against the PDF). Mapping to brewery streams is our assumption: water for brewing-water, CIP and condensate streams; product for mash, wort and beer; latent for boiling and boil-off condensation.

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| sweep: 100 EUR/m2 installed, linear (not a sourced estimate) | 0.1 | 377 | 1,201 | 651,888 |
| sweep: 250 EUR/m2 installed, linear (not a sourced estimate) | 0.3 | 311 | 1,204 | 658,570 |
| sweep: 500 EUR/m2 installed, linear (not a sourced estimate) | 0.5 | 281 | 1,207 | 668,157 |
| sweep: 1000 EUR/m2 installed, linear (not a sourced estimate) | 1 | 239 | 1,214 | 684,702 |
| sweep: 2000 EUR/m2 installed, linear (not a sourced estimate) | 2 | 198 | 1,228 | 712,480 |

## Provenance

- **stream data**: published (Table 2); 'Amb.' taken as 15 °C (Sec. 4.3.1), an inference
- **eta_lorenz**: published (Sec. 4.3.1, citing Andersen et al.)
- **source_T_C**: published cold-utility temperature (Sec. 4.1); used for all sources, which bounds W from above
- **sink levels**: published warm-water tank 18-82 °C (Fig. 14); HTHP at GCC maximum T* (assumed, consistent with COP 2)
- **basis**: assumed: 1.0 million hl/year, within the published range of Table 1 (0.25-1.5 million hl/year); economics at 8000 h/year (published)
- **ambient_T_C**: published: Sec. 4.3.1
- **area_targeting**: film coefficients: Stampfli et al. (2018) categories, mapping assumed; no sourced exchanger cost law: results given for a sweep of installed area cost
