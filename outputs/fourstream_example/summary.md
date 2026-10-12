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

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## Plausibility warnings

- **HTHP 200 °C**: sink 200 °C above 160 °C: limited commercial availability

## Provenance

- **stream data**: published (lecture notes, Example 1.1)
- **eta_lorenz**: assumed, same value as the brewery case (Padullés et al., 2026)
- **source_T_C**: assumed: 130 °C, below the pinch (T* 145 °C), where the process rejects heat
- **sink levels**: assumed, illustrative: 160 °C (commercial range) and 200 °C (upper end of IEA HPT Annex 58 scope)
- **basis**: none: the source gives no operating hours
- **ambient_T_C**: assumed: not given by the source
