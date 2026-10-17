# Four-stream chemical process

Chemical process with four streams (two reactor feeds and two products), loads in MW, with high-temperature heat demand.

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

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## Plausibility warnings

- **HTHP 200 °C**: sink 200 °C above 160 °C: limited commercial availability

## Sources and provenance

- **data source**: University of Oklahoma, ChE design course notes 'Minimum Utility', Example 1.1 (stream data and targets).
- **stream data**: published (lecture notes, Example 1.1)
- **eta_lorenz**: assumed, same value as the brewery case (Padullés et al., 2026)
- **source_T_C**: assumed: 130 °C, below the pinch (T* 145 °C), where the process rejects heat
- **sink levels**: assumed, illustrative: 160 °C (commercial range) and 200 °C (upper end of IEA HPT Annex 58 scope)
- **basis**: none: the source gives no operating hours
- **ambient_T_C**: assumed: not given by the source
- **economics**: assumed: no economic data in the source (see economics.sources)
- **film coefficients**: from the overall U of the University of Oklahoma notes (equal split)
- **eta_lorenz_sensitivity**: 0.45-0.52: Lorenz (Carnot) efficiencies implied by the DEA catalogue HTHP sheets 2.a/2.b (COP 4.45/2.75/2.4/2.05 at lifts of 40/65/80/100 K), as for the brewery
- **COP check**: eta_lorenz 0.55 (copied from the brewery) is above the 0.45-0.52 implied by the DEA catalogue: COP 7.94 at 30 K lift vs about 5.5-6 extrapolated from DEA (4.45 at 40 K); at 0.45 the NPV10 turns from +0.07 to -1.17 M€
- **steam sink**: assumed: the isothermal sink levels stand for steam mains (conventional for a chemical site; not stated by the source), so the DEA steam add-on applies
