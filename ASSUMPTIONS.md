# Assumptions and verifications register (brewery case, Padullés et al. 2026)

Status: **V** verified against a source or a known answer · **D** decision taken by the author ·
**C** conservative choice or advisory bound (cannot be verified; authors cannot be contacted) ·
**L** documented limitation of a source. Closed 2026-10-14. Sensitivities: `outputs/brewery_padulles2026/rq_consolidated.md`.

| # | Item | Status | Basis / effect |
|---|---|---|---|
| 1 | "Amb." in Table 2 = 15 °C | D | Author decision (Sec. 4.3.1 value). Fig. 4 suggests about 11 °C; effect about 0.1 kWh/hl per K |
| 2 | Q̇c,min 3.44 vs published 3.2 kWh/hl | L, C | Rounding in Table 2. A lower Q̇c lowers the refrigeration credit by ≤ 7 %: covered by the 50 % credit row |
| 3 | Gas emission factor | C | IPCC 2006 combustion value 0.182 kg/kWh (GCV) used; the paper's 0.219 (scope not stated) is a sensitivity. Lower factor = fewer t CO₂ claimed |
| 4 | Tank size scaling (DK1 / DK2 mismatch) | C | Tank scaled from 375 m³ at 0.72 Mhl → 520.8 m³ at 1 Mhl: the larger, dearer reading |
| 5 | High-temperature heat pump covers wort preheating (0.6 kWh/hl) | C | Included (3.0 vs paper's 2.4 kWh/hl): more capex and electricity than the paper |
| 6 | Cycle model vs Andersen Fig. 2 (+17 %) | C | Advisory row "cycle-based COP −17 %"; Appendix A cases within −5 to +6.5 %; MAN HPU43 vendor COP 3.05 vs ours 2.4–2.7 (ours lower) |
| 7 | MVR COP 15 vs η 0.55 (paper) | L | MVR not used in the final options |
| 8 | Two-stage cycles | V | Implemented; Andersen App. A: R-1234ze(E) two-stg −0.1 %, water two-stg2 −5.0 % |
| 9 | Practical compressor limits | V, C | IEA HPT Annex 58 Task 1, Table 1-3: pressure ratio per stage ≤ 10 (piston/scroll; screw > 20, so 10 is conservative); ammonia ≤ 76 bar, 110 °C. Selected: propane SLHX (warm water, COP 3.11), propane/butane cascade (HTHP, COP 1.96) |
| 10 | Film coefficients (Stampfli dairy categories) | V | Implied U: water–water 1000, product–water 400, condensing–water 1430 W/m²K, inside Sinnott & Towler Table 12.1 shell-and-tube ranges (plates are higher, so areas are conservative) |
| 11 | Gas prices on GCV; NCV/GCV = 0.90 | V | Regulation (EU) 2016/1952, Annex I, point 4; IPCC (1996) Reference Manual, Ch. 1, Table 1-4 note a |
| 12 | Electricity tariff band ID | V, C | IFC EHS Guidelines for Breweries (2007): 7.5–11.5 kWh/hl → 11–15 GWh/y with heat pumps. ID is also dearer than IE (conservative) |
| 13 | Exchange rates | V | ECB Data Portal: NZD 2017 = 1.5897 (annual); USD 2023 = 1.0816 (mean of monthly averages) |
| 14 | Cost escalation | V | CEPCI 2017 = 567.5, 2023 = 797.9 (Chem. Eng., Sept. 2024, p. 45); latest monthly May 2024 = 800.2 (+0.3 %, not applied) |
| 15 | Exchanger cost law | V | Sinnott & Towler Table 6.6 (plate and frame) × 3.5 (Hand, Table 6.3); Stampfli kept as cross-check only (does not match Bouman 2005) |
| 16 | Location factor for Portugal | L | Not in Sinnott & Towler Table 6.7; none applied |
| 17 | Chiller COP 4.45 | V | 0.6 × Carnot (Sinnott & Towler Sec. 6.4.4); CoolProp NH₃ 4.52. Range 3.14 (Example 6.7, 40 °C cooling water) to 6.68 |
| 18 | Refrigeration credit simultaneity | C | Paper's continuous operation (8000 h) gives full credit; advisory rows: 50 % and none |
| 19 | Heat pump capex | V | Padullés Table 3 (1.12 M€/MW at 1 MW) vs DEA sheet 2.a 1.2 (0.9–1.5) M€/MW: ±25 % rows. Fixed O&M ≈ 2 k€/MW·y (DEA 1.1/1.2), < 1 % of savings, neglected |
| 20 | Production 1 Mhl/y | C | Within Padullés Table 1; rows at 0.25, 0.5, 1.5 Mhl/y |
| 21 | New condensate exchanger (4 K, U = 1.0) and tank ∝ heat | C | Stress test: exchanger capex ×3 |
| 22 | ΔTmin,opt 0.4–1.0 K | C | Lower bound: pumping, fouling and batch timing not modelled; Sinnott & Towler give 10–30 K typical |
| 23 | App: upload, bad input, cell edit | V | `ui_smoke.py` (browser): upload OK; missing columns reported; CP 0.2 → 0.3 gives Q̇h 13.5 MW = problem-table value |
| 24 | Dairy cases: economics | L | Walmsley et al. (2024) give no operating hours or prices: steps 1–4 only. Network/retrofit generality tested on the four-stream example |
| 25 | Spray dryer first-law inconsistency | L | Published targets reproduced only with inferred temperatures (Fig. 5) |
| 26 | Walmsley evaporator ΔTcont 0.5 vs 2.5 K | L | Targets unaffected |
