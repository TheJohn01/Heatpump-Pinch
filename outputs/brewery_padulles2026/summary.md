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

Price ratio 2.4 (electricity 0.132 EUR/kWh, gas 0.055 EUR/kWh); boiler efficiency 1.0; 8000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 1,793,176 |
| Full design: annual savings [EUR/year] | 98,190 |
| Full design: simple payback [years] | 18.2622 |
| Full design: NPV [EUR] | -1,034,976 |
| Full design: CO2 avoided [t/year] | 1,796 |
| Full design: primary-energy reduction | 34.9 % |
| RQ1: largest share of Q̇h,min with payback ≤ 5 y | 0.0 % |
| RQ1: share with maximum NPV | 0.0 % |
| RQ3: break-even ratio, NPV = 0 | 1.692 |
| RQ3: break-even ratio, payback = threshold | 1.024 |

## Provenance

- **stream data**: published (Table 2); 'Amb.' taken as 15 °C (Sec. 4.3.1), an inference
- **eta_lorenz**: published (Sec. 4.3.1, citing Andersen et al.)
- **source_T_C**: published cold-utility temperature (Sec. 4.1); used for all sources, which bounds W from above
- **sink levels**: published warm-water tank 18-82 °C (Fig. 14); HTHP at GCC maximum T* (assumed, consistent with COP 2)
- **basis**: assumed: 1.0 million hl/year, within the published range of Table 1 (0.25-1.5 million hl/year); economics at 8000 h/year (published)
- **ambient_T_C**: published: Sec. 4.3.1
