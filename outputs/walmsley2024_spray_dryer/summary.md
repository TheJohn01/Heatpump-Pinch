# walmsley2024_spray_dryer

Milk powder spray dryer (main air chamber, static and vibrating fluid beds, exhaust air with heat recovery). Loads in kW. Table 1 data as published.

Source: Walmsley, Lincoln, Padullés, Cleland (2024), Energies 17, 2838, Table 1 (case first presented by Liang et al.).

## Energy targets

| Quantity | Value [kW] |
|---|---|
| Total hot / cold stream loads | 6869.0 / 6031.0 |
| Q̇h,min | 4638.2 |
| Q̇c,min | 5476.2 |
| Heat recovery | 1392.8 |
| Pinch T* [°C] | 59.0 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | HTHP 120 °C (fluid beds), HTHP 200 °C (main air) |
| Heat delivered [kW] | 3732.5033 |
| Electricity [kW] | 2446.3752 |
| System COP [-] | 1.526 |
| Residual hot utility [kW] | 905.6967 |
| Share of Q̇h,min electrified | 80.5 % |
| External (ambient) source [kW] | 0.0 |

## Annual figures [MWh/year]

Basis: {'type': 'power', 'operating_hours_per_year': 6000}

Q̇h,min 27829.2; Q̇c,min 32857.2; heat pump electricity 14678.3; residual hot utility 5434.2.

## Economics (step 6)

Price ratio 2.016 (electricity 0.0897 EUR/kWh, gas 0.0445 EUR/kWh); boiler efficiency 0.845; 6000 h/year.

| Quantity | Value |
|---|---|
| Full design: CAPEX [EUR] | 6,134,727 |
| Full design: annual savings [EUR/year] | -199,641 |
| Full design: simple payback [years] | inf |
| Full design: NPV [EUR] | -7,676,306 |
| Full design: CO2 avoided [t/year] | 3,253 |
| Full design: primary-energy reduction | -13.6 % |
| Grass-roots reference (not the RQ1 answer): heat pumps' share of Q̇h,min at target, payback ≤ 5 y | 0.0 % |
| Grass-roots reference: share with maximum NPV | 0.0 % |
| Grass-roots reference: break-even ratio of the full design, NPV = 0 | 0.494 |
| Grass-roots reference: break-even ratio, payback = threshold | -0.168 |

RQ1-RQ3 answers for a site with an existing network (share of today's gas, incremental payback, break-even ratio per unit) are in the retrofit section and in rq_consolidated.md.

### Sensitivities, grass-roots reference (economics rows of the case's sensitivity list)

Same rows and labels as rq_consolidated.md, which gives RQ1-RQ3 against today's site.

| Sensitivity | Ratio | Full-design payback [y] | NPV [EUR] | CO2 avoided [t/y] | HP share of Q̇h,min, payback ≤ threshold | Full-design break-even ratio (NPV = 0) |
|---|---|---|---|---|---|---|
| with hot-water piping (DEA indirect cost) | 2.016 | inf | -7,840,359 | 3,253 | 0.0 % | 0.461 |

### Lorenz-efficiency sensitivity (heat pumps re-sized)

| η_L | System COP | Full-design payback [y] | NPV [EUR] | Grass-roots HP share, payback ≤ threshold | Full-design break-even ratio (NPV = 0) |
|---|---|---|---|---|---|
| 0.45 | 1.373 | inf | -8,805,944 | 0.0 % | 0.444 |
| 0.52 | 1.587 | inf | -7,285,278 | 0.0 % | 0.514 |

## ΔTmin supertargeting (step 3, RQ2)

Hot utility 315.98 EUR/kW-year; cold utility 0.0 EUR/kW-year; CRF 0.1295/year. Film coefficients: Liang et al. (2022), Table 2 (from Zühlsdorf et al.): overall U water-air 42.5 W/(m2 K) on the air-side area. Air-air heat transfer is done through water loops (direct air-air exchange is not used in practice, Sec. 2.1), i.e. two water-air exchangers in series: h = 0.0425 kW/(m2 K) per air stream gives U = 21 W/(m2 K) per match

| Cost law | ΔTmin,opt [K] | Area [m²] | Q̇h,min [kW] | TAC [EUR/year] |
|---|---|---|---|---|
| sweep: 25 EUR/m2 installed, linear (not a sourced estimate) | 2 (grid edge) | 17,482 | 4,143 | 1,365,575 |
| sweep: 50 EUR/m2 installed, linear (not a sourced estimate) | 4 | 12,518 | 4,202 | 1,408,658 |
| sweep: 100 EUR/m2 installed, linear (not a sourced estimate) | 8 | 7,870 | 4,329 | 1,469,677 |
| sweep: 250 EUR/m2 installed, linear (not a sourced estimate) | 14 | 4,440 | 4,561 | 1,584,848 |

## Plausibility warnings

- **HTHP 200 °C (main air)**: sink 200 °C above 160 °C: limited commercial availability; lift 185 K above 130 K: beyond reported COP data

## Provenance

- **stream data**: published (Table 1). WARNING: Table 1 is inconsistent with the paper's own targets (4.98 / 3.99 MW) by the first law; see verify_walmsley2024.py
- **eta_lorenz**: published: 50 % exergetic efficiency (Sec. 4.2)
- **source_T_C**: assumed: 15 °C (dead state), where the cooled exhaust air ends
- **sink levels**: assumed, illustrative: 120 °C (fluid beds) and 200 °C (upper end of IEA HPT Annex 58 scope); the main air chamber up to 236 °C stays on fired heating
- **basis**: published: 6000 h/year, Liang et al. (2022), 'Full electrification opportunities of spray dryers in milk powder processes', ECOS 2022, Copenhagen (DTU accepted manuscript, peer-reviewed): the source of the stream data in Walmsley et al. (2024) Table 1 (GEA Process Engineering, skim milk powder dryer), Sec. 2.1
- **ambient_T_C**: published: dead state 15 °C (Sec. 2)
- **economics**: assumed: no economic data in the source (see economics.sources)
- **film coefficients**: Liang et al. (2022), Table 2 (from Zühlsdorf et al.): overall U water-air 42.5 W/(m2 K) on the air-side area. Air-air heat transfer is done through water loops (direct air-air exchange is not used in practice, Sec. 2.1), i.e. two water-air exchangers in series: h = 0.0425 kW/(m2 K) per air stream gives U = 21 W/(m2 K) per match
- **eta_lorenz_sensitivity**: 0.45-0.52: Lorenz (Carnot) efficiencies implied by the DEA catalogue HTHP sheets 2.a/2.b (COP 4.45/2.75/2.4/2.05 at lifts of 40/65/80/100 K), as for the brewery
- **COP check**: HTHP 120 °C (105 K lift): COP 1.87 vs DEA sheet 2.a about 1.96 at 105 K (-4.6 %, conservative). HTHP 200 °C: COP 1.28 from a 15 °C source; Liang et al. (2022) use the exhaust (via water loops) as source and reach COP 2.61 for the steam heat pump, Liang et al. (2023, IIR ICR) a total COP of 2.68 with a transcritical CO2 cycle: the illustrative isothermal design here is pessimistic
