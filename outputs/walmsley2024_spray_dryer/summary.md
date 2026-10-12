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

No annual basis given: results stay in the stream-data unit.

## Plausibility warnings

- **HTHP 200 °C (main air)**: sink 200 °C above 160 °C: limited commercial availability; lift 185 K above 130 K: beyond reported COP data

## Provenance

- **stream data**: published (Table 1). WARNING: Table 1 is inconsistent with the paper's own targets (4.98 / 3.99 MW) by the first law; see verify_walmsley2024.py
- **eta_lorenz**: published: 50 % exergetic efficiency (Sec. 4.2)
- **source_T_C**: assumed: 15 °C (dead state), where the cooled exhaust air ends
- **sink levels**: assumed, illustrative: 120 °C (fluid beds) and 200 °C (upper end of IEA HPT Annex 58 scope); the main air chamber up to 236 °C stays on fired heating
- **basis**: none: operating hours not given
