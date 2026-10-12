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

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## Provenance

- **stream data**: published (Table 2); Table 2 dT_cont used (chiller water 0.5 K; the text's pinch range implies 2.5 K, which leaves the targets unchanged)
- **eta_lorenz**: published: 50 % exergetic (Carnot) efficiency (Sec. 4.2); reproduces the paper's simple-design COP 2.1
- **source_T_C**: published: ambient / dead state 15 °C (Sec. 2), the source of the paper's simple design
- **sink levels**: 105 °C published (simple design, Sec. 4.2.3); the 15-55 °C level is assumed (illustrative, follows the low-temperature part of the GCC)
- **basis**: none: operating hours not given
- **ambient_T_C**: published: dead state 15 °C (Sec. 2)
