# Engineering validation (tests)
Compared with theory: divider 2.5 V; LED ~10 mA; RC at 1 tau = 63.2%; RC AC -3.01 dB at fc; op-amp gain 10; NPN/MOSFET on/off levels; relay spike clamped (<14.5 V) vs unclamped (>50 V); KiCad netlist round-trip on all 7 templates; KiCad DRC clean on the 6 PCB-capable templates and detects deliberately removed tracks; rating violations; unconnected pins; calculator error cases.

Also verified: PMOS off/on = 0 V / ~Vcc; PNP conducts; DC sweep of a divider is Vin/2; parameter sweep matches Vin*R2/(R1+R2); divider optimizer picks 20 kOhm (error 1.01%) and honestly reports the 1% tolerance as not met, met at 2%; imports cannot carry simulation claims; hostile AI operations (bad kind, unsafe net names) are rejected.

Also verified: behavioral LDO holds 4.995 V at 100 mA from 9 V, drops out to Vin-2 V at 5.5 V in (dropout warning raised from simulated voltages), dissipation warning at 12 V in; KiCad round-trip and DRC for the regulator template; frontend net-editing logic (connect, merge with ground priority, disconnect, ground, no name collisions) and the click-two-pins wiring flow.

Also verified: op-amp with a 5 V rail gives 3.0 V for an in-range input and clamps at 5.0 V when the ideal answer would be 6 V, raising an `opamp.saturated` warning from simulated voltages; without rails it stays ideal (6.0 V).

Also verified: PCB-area optimizer builds 8 layouts (10-25 mm pitch) and accepts only KiCad-DRC-clean ones (for the NPN circuit pitch 14 mm passes, 12 and 10 mm fail with 2 and 14 errors; 36.9% smaller); applying the suggested pitch reproduces the measured board size; every part in layout.json lies on the board. PostgreSQL 16: all migrations and the whole backend suite pass.
