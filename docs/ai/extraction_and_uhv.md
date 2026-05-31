# Gas Extraction & UHV System — Domain Primer for Agents

Third companion to `docs/ai/arar_geochronology.md` (the science) and
`docs/ai/noble_gas_mass_spectrometer.md` (the detector). This one covers the
**front end**: the ultra-high-vacuum (UHV) gas-handling line that releases argon
from a sample, cleans it, and delivers a known aliquot to the spectrometer.

Read it before editing `pychron/extraction_line`, `pychron/furnace`,
`pychron/lasers`, or the vacuum/heater/laser device classes under
`pychron/hardware`. It explains *why* valves, gauges, PID controllers, and laser
managers exist and how they map to the code.

---

## 1. Why a UHV extraction line exists

Argon abundances in a sample are minuscule, and the **atmosphere is ~1% argon**.
A single air leak swamps the signal. So the entire gas path is held at
ultra-high vacuum (≲1e-8 torr) and the sample gas is isolated, heated, purified,
and measured without ever touching air. The extraction line is the plumbing that
does this: a manifold of chambers connected by **valves**, monitored by
**gauges**, evacuated by **pumps**, with sample heated by a **furnace** or
**laser**.

The package owns exactly this. From `pychron/extraction_line/README.md`:
pneumatic valves, vacuum gauges, cryo/heaters, pumps, manometers, pipette
tracking, sample changer, a 2D canvas of live valve state, and a graph topology
for volume/path calculations.

A typical run sequence: isolate a clean section → admit sample gas → heat
(extract) → expose to **getters** (chemically absorb non-noble gases) → let
argon equilibrate → admit to the spectrometer → measure → pump away.

---

## 2. Valves / switches — the plumbing

`pychron/extraction_line/switch_manager.py` (engine),
`pychron/hardware/valve.py` (`HardwareValve`), `section.py` (groups).

Valves are mostly **pneumatic**: a solenoid admits compressed air to open/close
the valve; the controller may read back an indicator of actual position.

| Concept | Code | Meaning |
|---------|------|---------|
| State | `HardwareValve.state` (True=open) | open/closed; persisted across restarts |
| Software lock | `software_lock` | block actuation in software even if hardware could move |
| Interlock | `SwitchManager` interlock checks | refuse to open a valve if a conflicting valve is open (prevents venting UHV to atmosphere) |
| Ownership | manager ownership/`StatusMonitor` | in multi-client setups, who is allowed to actuate |
| Double actuation | `DoubleActuationValve` | separate open/close channels + delays |
| State word | `ClientSwitchManager` | remote reads a packed bitfield of all valve states |

`ExtractionLineGraph` (`graph/extraction_line_graph.py`) models the line as
nodes (valves, pumps, chambers) and edges; `traverse.py` does BFS that **stops
at closed valves**, so the system can compute which chambers are connected, the
total expansion volume, and whether a path to a pump or the spectrometer is open.
This volume/topology matters scientifically: it sets gas expansion ratios and
guards against accidentally opening the sample to a pump.

---

## 3. Vacuum gauges & pumps — measuring and maintaining UHV

`pychron/extraction_line/gauge_manager.py`, `manometer_manager.py`,
`pump_manager.py`, gauge drivers under `pychron/hardware/gauges/`.

- **Ion gauge** (hot/cold cathode) — measures UHV pressure (≲1e-3 torr down to
  ~1e-10). Vendors: `granville_phillips`, `mks`, `pfeiffer`, `varian`,
  `igc100_gauge_controller.py`. Base: `gauges/base_controller.py`,
  `base_gauge.py`; reads a `pressure`.
- **Convection / Pirani gauge** — rough-to-medium vacuum (atmosphere down to
  ~1e-3 torr); used during pump-down.
- **Manometer** (`manometer_manager.py`) — capacitance/absolute pressure, e.g.
  for measured gas aliquots.
- **Pumps** (`pump_manager.py`, `pychron/hardware/ionpump`) — ion pumps and
  turbo pumps maintain the vacuum; their current/pressure is also a vacuum
  health proxy.

Pressure readings gate the workflow: don't admit sample to the spectrometer, or
fire the laser, unless vacuum is good. `status_monitor.py` polls hardware in a
background thread so multiple clients see live state.

---

## 4. Furnaces & PID temperature control — bulk heating

`pychron/furnace`, `pychron/hardware/pid_controller.py`,
`pychron/hardware/eurotherm/`.

A resistance furnace heats a sample (often in a metal crucible) to release gas,
in **incremental temperature steps** (the step-heating that yields age spectra,
see arar primer §5) or to a single high temperature (total fusion).

Temperature is held by a **PID controller** — a closed feedback loop that drives
heater output so the measured temperature tracks a target:

- **Setpoint** — the target temperature you command (`set_setpoint`).
- **Process value** — the measured temperature (`get_process_value`).
- **Output** — % power the loop applies to the heater (`get_output`).
- **PID gains** Kp/Ki/Kd — proportional/integral/derivative terms; `set_pid`
  tunes how aggressively/stably the loop converges (`IFurnaceController` in
  `furnace/ifurnace_controller.py`).

Hardware backends: `PidController` wraps a **Eurotherm** controller
(`pychron/hardware/eurotherm/`); vendor furnaces live in `furnace/nmgrl`,
`furnace/thermo`, `furnace/ldeo`, `furnace/reston`.
`configure_dump.py` handles dropping the sample into the hot furnace
(sample-drop/dump mechanism). Bad PID tuning = temperature overshoot/oscillation
= wrong gas-release temperature = a smeared age spectrum.

---

## 5. Laser extraction devices — spot/step heating

`pychron/lasers/laser_managers/`. A laser heats a small spot (single grain or a
sub-region of a sample), enabling spatially-resolved dating and fast fusion.
Manager hierarchy: `BaseLaserManager` → `LaserManager` → device-specific.

Laser types and managers:
- **CO₂** (10.6 µm, bulk silicate heating) — `fusions_co2_manager.py`,
  `synrad_co2_manager.py`, `uc2000_laser_manager.py`.
- **Diode** (continuous, temperature-controlled heating) —
  `fusions_diode_manager.py`.
- **UV / excimer** (ablation, micro-sampling) — `fusions_uv_manager.py`,
  `ablation_laser_manager.py`, `uv_gas_handler_manager.py`.

Two control modes (`laser_manager.py`):
- **Power / open loop** — `set_laser_power(power)` sets % output directly.
  `enable_laser()` / `disable_laser()` arm/disarm; `emergency_shutoff` for
  safety.
- **Temperature / closed loop** — `WatlowMixin` /
  `TemperatureControllerLaserMixin` (`watlow_mixin.py`) run a **PID loop on a
  measured temperature** (`set_laser_temperature`, `set_{mode}_loop_setpoint`,
  `set_pid`), with the temperature read by a **pyrometer**
  (`pyrometer_mixin.py`). This is the same setpoint/process-value/output PID
  concept as the furnace (§4), applied to laser output.

Supporting: `stage_managers/` (XY/Z sample positioning), `pattern/` and
`points/` (raster/scan patterns over a sample), `power/` (power calibration,
mapping requested → actual watts).

---

## 6. Where this feeds the rest of Pychron

- Extraction + measurement are **scripted** per run by `pychron/pyscripts`
  (extraction script controls valves/laser/furnace; measurement script controls
  the spectrometer) and sequenced by `pychron/experiment`.
- The gas this system delivers is what the spectrometer measures
  (`noble_gas_mass_spectrometer.md`) and what the reduction math turns into an
  age (`arar_geochronology.md`).
- **Blanks** (arar primer §3) are the argon this line contributes on its own —
  which is why line cleanliness, getter health, and vacuum quality directly
  affect data quality.

---

## 7. Pitfalls for an editing agent

- **Interlocks and software locks are safety, not UI niceties.** Don't bypass
  valve interlock checks; opening the wrong valve can vent UHV or destroy a
  filament/ion gauge.
- `ExtractionLineGraph` traversal **stops at closed valves** by design — that is
  how connectivity/volume is computed; don't "fix" it to cross closed valves.
- Client vs server managers (`Client*` classes) read state remotely via state
  words; keep the two paths in sync when changing valve state handling.
- Furnace and laser-diode both use **PID** with the same setpoint/process-value/
  output/Kp-Ki-Kd vocabulary — don't assume "laser" means open-loop power only.
- `enable_laser`/`disable_laser` and `emergency_shutoff` are safety-critical;
  preserve disable-on-error paths.
- Pressure/temperature readbacks gate downstream actions; don't remove the vacuum
  checks that guard spectrometer inlet or laser firing.
