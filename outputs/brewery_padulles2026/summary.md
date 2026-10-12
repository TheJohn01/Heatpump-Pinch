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

No annual basis given: results stay in the stream-data unit.

## Provenance

- **stream data**: published (Table 2); 'Amb.' taken as 15 °C (Sec. 4.3.1), an inference
- **eta_lorenz**: published (Sec. 4.3.1, citing Andersen et al.)
- **source_T_C**: published cold-utility temperature (Sec. 4.1); used for all sources, which bounds W from above
- **sink levels**: published warm-water tank 18-82 °C (Fig. 14); HTHP at GCC maximum T* (assumed, consistent with COP 2)
- **basis**: none: the paper gives no production volume for the reference brewery
