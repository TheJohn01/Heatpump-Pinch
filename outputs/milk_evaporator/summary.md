# Milk evaporator

Dairy milk evaporator: two-effect MVR evaporation with milk heat treatment, 247 t/h raw milk (30 t/h milk powder); evaporation system in isolation. Loads in kW.

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

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## COP ranges from manufacturer and demonstration data (step 4, pinch.cop_data)

COP of each heat pump on four bases: the case's Lorenz efficiency; manufacturer-data fits (Jesper et al. 2021) at lift = sink outlet - source inlet, with their standard deviation; a glide-matched blend (+16 %, Brendel et al. 2024) for sink glides of 25 K or more; the Lorenz model with the efficiencies achieved by IEA HPT Annex 58 closed-cycle demonstration plants (min, median, max). The fits come from small-glide machines, so for a large sink glide they are a pessimistic bound. fit_in_range = False: the point is outside the data behind the fit.

| Unit | Lift [K] | Sink glide [K] | Case basis | Fit −σ / fit / +σ | In fit range | Glide blend | Demonstration η_L min / median / max |
|---|---|---|---|---|---|---|---|
| HP warm (milk preheat) | 40 | 40 | 7.86 | 3.70 / 3.98 / 4.26 | yes | 4.62 | 5.44 / 5.83 / 8.57 |
| HTHP 105 °C | 90 | 0 | 2.10 | 1.76 / 1.95 / 2.14 | no (extrapolated) | – | 1.45 / 1.56 / 2.29 |

## Sources and provenance

- **data source**: Walmsley, Lincoln, Padullés, Cleland (2024), Energies 17, 2838, Table 2.
- **stream data**: published (Table 2); Table 2 dT_cont used (chiller water 0.5 K; the text's pinch range implies 2.5 K, which leaves the targets unchanged)
- **eta_lorenz**: published: 50 % exergetic (Carnot) efficiency (Sec. 4.2); reproduces the paper's simple-design COP 2.1
- **source_T_C**: published: ambient / dead state 15 °C (Sec. 2), the source of the paper's simple design
- **sink levels**: 105 °C published (simple design, Sec. 4.2.3); the 15-55 °C level is assumed (illustrative, follows the low-temperature part of the GCC)
- **basis**: none: operating hours not given
- **ambient_T_C**: published: dead state 15 °C (Sec. 2)
- **economics**: assumed: no economic data in the source (see economics.sources)
- **film coefficients**: Stampfli et al. (2018) dairy values, stream mapping assumed
- **eta_lorenz_sensitivity**: 0.45-0.52: Lorenz (Carnot) efficiencies implied by the DEA catalogue HTHP sheets 2.a/2.b (COP 4.45/2.75/2.4/2.05 at lifts of 40/65/80/100 K), as for the brewery
- **COP check**: HTHP 105 °C (steam, 90 K lift): COP 2.10 vs DEA sheet 2.a 2.22 at 90 K minus 0.15 for steam = 2.07 (+1.5 %). Warm-water heat pump 15 -> 55 °C: Lorenz COP 7.86 vs DEA sheet 1.1 'up to 60 °C, lift 40 K' 5.33 (+47 %; the Lorenz model credits the full 40 K sink glide, which needs a glide-matched cycle such as transcritical CO2); with COP 5.33 RQ1 falls from 26 % to 23 %
- **steam sink**: verified: the 105 °C level supplies the Direct Steam Injection that follows the 8 -> 95 °C preheat (Walmsley et al. 2024, Sec. 3.2), so the DEA steam-generation add-on applies
