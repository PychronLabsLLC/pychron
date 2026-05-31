# Noble-Gas Mass Spectrometer — Domain Primer for Agents

Companion to `docs/ai/arar_geochronology.md` (the *science* — turning argon
isotopes into ages) and `docs/ai/extraction_and_uhv.md` (the *front end* — the
UHV line that extracts and delivers the gas). This one covers the *instrument*
that measures those isotopes. Read it before editing `pychron/spectrometer`,
`pychron/spectrometer/ion_optics`, `pychron/spectrometer/jobs`, or detector/
magnet/source device code — it explains *why* parameters like resolution,
sensitivity, peak center, deflection, and acceleration voltage exist and how
they map to the code.

---

## 1. What the instrument is

A noble-gas mass spectrometer measures the abundance of each argon isotope
(masses 40, 39, 38, 37, 36) in a tiny purified gas sample. These are
**static-vacuum sector** instruments: the gas is trapped in a sealed analyzer
(no continuous pumping during measurement) so vanishingly small noble-gas
signals can be integrated over time.

Physical path of an ion:

```
 gas → ion SOURCE (ionize + accelerate + focus) → flight tube
     → MAGNET (mass disperse by m/z) → DETECTOR (collect ion current)
```

Supported vendor backends live in sibling packages, each with `source/`,
`magnet/`, `detector/`, `spectrometer/`, `manager/`:
`pychron/spectrometer/thermo` (Thermo: Argus, Helix, MAT253),
`pychron/spectrometer/isotopx` (NGX), `pychron/spectrometer/pfeiffer`.
Vendor-neutral base classes: `base_spectrometer.py`, `base_source.py`,
`base_magnet.py`, `base_detector.py`.

---

## 2. The ion source — making and shaping the beam

Electrons from a filament ionize neutral argon; electrostatic optics extract,
accelerate, and focus the ions into a beam. Source parameters
(`base_source.py`, `thermo/source/base.py`, `helix.py`) are tuned to maximize
**sensitivity** (ions delivered to the detector per atom in the source) and
**beam shape** (flat-topped, symmetric peaks):

| Parameter (trait) | Physical meaning |
|-------------------|------------------|
| `nominal_hv` / `set_hv` / `read_hv` | **Acceleration (high) voltage** (~kV). Accelerates ions to a fixed kinetic energy. Defines the m/z↔magnet-field relationship; an HV scan can center a peak instead of moving the magnet (`AccelVoltagePeakCenter`, `hv_sweep.py`). |
| `trap_current` | Filament emission regulator → controls electron flux that does the ionizing. More trap current ≈ more ionization ≈ more sensitivity (until saturation). |
| `trap_voltage` | Potential confining electrons in the ionization region. |
| `emission` | Readback of actual electron emission current — a health/sensitivity indicator. |
| `extraction_lens` | Pulls ions out of the ionization volume into the optics. |
| `y_symmetry`, `z_symmetry` | Steer/center the beam transverse to flight (peak shape, flat top). |
| `vertical_deflection_n/s`, `flatapole`, `rotation_quad` (Helix) | Higher-order ion-optics: deflect/rotate/shape the beam for multi-collector alignment. |
| `electron_energy` (vendor) | Filament electron energy; affects ionization efficiency and fragmentation of interfering species. |

**Sensitivity** = signal per unit gas (e.g. A/mol, or cps/fA per atom). It sets
the smallest sample datable and drifts as the source ages; tracked and used to
normalize signals.

---

## 3. The magnet — separating masses

A sector magnet bends ions on a radius set by mass, charge, velocity, and field
strength. At fixed HV, **field ∝ √(m/z)**, so scanning the field (via a DAC
voltage) sweeps different masses across a detector.

`base_magnet.py` core API:
- `dac` — the DAC voltage (0–10 V) that commands magnet field.
- `mass` — the mass currently centered on the reference detector.
- `map_mass_to_dac(mass, detname)` / `map_dac_to_mass(dac, detname)` — convert
  between amu and DAC **per detector**, because each collector sits at a
  different physical position.

These mappings come from the **MFTABLE** (magnet field table): a per-detector
calibration of DAC↔mass, built/maintained by `mftable_generator.py`,
`auto_mftable.py`, `field_table.py`, `mass_cal/mass_calibrator.py`. Editing
magnet code without respecting the MFTABLE will mis-position every peak.

---

## 4. The detectors — collecting ion current

`base_detector.py`. Two collector types (`kind`):

- **Faraday cup** — measures beam current as a voltage across a large resistor.
  Robust, linear, for big beams (e.g. ⁴⁰Ar, ³⁹Ar).
- **Ion counter / CDD** (electron multiplier / "compact discrete dynode") —
  counts individual ions; ultra-sensitive, for tiny beams (e.g. ³⁶Ar). Has an
  operating high voltage tuned via `cdd_operating_voltage_scan.py`.

Detector concerns in code:
- `gain` / `software_gain` — amplification factor; relative gains are why an
  **IC factor** (inter-calibration) is needed (see arar primer §3) so different
  detectors are comparable.
- `deflection` / `use_deflection` / `deflection_correction_sign` — small per-cup
  electrostatic steering so each collector sits exactly on its peak;
  calibrated by `thermo/deflection.py` (`DeflectionCalibration`).
- `protection_threshold` — guards a sensitive ion counter from large beams.
- A multicollector measures several masses simultaneously on an array of cups;
  a single-collector ("peak hopping") instrument steps the magnet to each mass
  in turn.

---

## 5. Resolution & resolving power

**Resolution** describes how well two adjacent masses are separated, i.e. how
sharp the peak edges are. In a sector instrument it is set by source/collector
slit widths and beam focus.

Pychron computes it from a peak-center scan (`pychron/core/stats/peak_detection.py`):

- `calculate_resolution(x, y)` → `res = cx / (hx − lx)` — center DAC divided by
  the peak width at 95% of max. Higher = sharper peak.
- `calculate_resolving_power(x, y)` — measured from the low- and high-mass
  edges between 5% and 95% of peak height; reports the rising/falling-edge
  resolving power separately.

Why it matters scientifically: ⁴⁰Ar from ³⁶Ar / hydrocarbon / doubly-charged
interferences must be resolved or accounted for. Low resolution = peaks overlap
= biased isotope ratios = wrong ages.

---

## 6. Peak centering

`pychron/spectrometer/ion_optics/`, `pychron/spectrometer/jobs/peak_center.py`.

A **peak center** finds the magnet DAC (or HV) at which an isotope's beam sits
squarely on a detector, so the measurement integrates the flat top of the peak
rather than a sloping flank (where tiny field drift would change the signal).

- `BasePeakCenter.get_peak_center()` sweeps the magnet across a reference mass,
  records intensity vs DAC, and locates the center.
- `PeakCenter(MagnetSweep)` moves the magnet; `AccelVoltagePeakCenter(AccelVoltageSweep)`
  moves HV instead.
- `_calculate_peak_center` → `calculate_peak_center` / `calculate_peak_center_pseudo`
  in `peak_detection.py` return `[low, center, high]` DAC positions; `PeakCenterResult`
  also carries `resolution`.
- Config/UI: `peak_center_config.py`, `define_peak_center_view.py`,
  `coincidence_config.py` (aligning multiple detectors on the same mass —
  **coincidence** — via `jobs/coincidence.py`).

Peak centering is run routinely before/within an analysis; if the center is
wrong, every subsequent intensity is wrong.

---

## 7. Scans & tuning jobs

`pychron/spectrometer/jobs/` — diagnostic/calibration sweeps, mostly subclasses
of `BaseSweep`/`BaseScanner`:

| Job | Sweeps | Purpose |
|-----|--------|---------|
| `magnet_scan.py` / `magnet_sweep.py` | magnet DAC | see the spectrum / locate masses |
| `mass_scanner.py` | mass | spectrum vs amu |
| `peak_center.py` | magnet or HV | center a peak (§6) |
| `hv_sweep.py` (`HVSweep`) | acceleration voltage | HV-based centering/tuning |
| `cdd_operating_voltage_scan.py` | ion-counter HV | set CDD operating plateau |
| `dac_scanner.py` | arbitrary DAC | generic source/optics tuning |
| `coincidence.py` | — | align detectors on one mass |

`scan_manager.py` and `readout_view.py` drive live scanning/monitoring;
`spectrometer_parameters.py` holds the editable parameter set.

---

## 8. Pitfalls for an editing agent

- **DAC vs mass are not interchangeable** — always go through the MFTABLE
  (`map_mass_to_dac`/`map_dac_to_mass`); each detector has its own mapping.
- **Field ∝ √(m/z) at fixed HV** — changing HV shifts where masses land; HV and
  magnet are two ways to center the same peak.
- Source parameters interact: trap current ↔ sensitivity ↔ beam shape ↔
  resolution. A change tuned for signal can degrade peak flatness.
- Don't conflate **gain** (detector amplification, → IC factor) with
  **sensitivity** (source ionization efficiency, → smallest datable sample).
- Vendor backends differ in commands and available parameters; edit the base
  class only when behavior is genuinely shared, otherwise patch the specific
  `thermo/`, `isotopx/`, or `pfeiffer/` implementation.
- Static-vacuum operation means signals decay/grow during measurement (memory,
  pumping, blank growth); time-zero extrapolation is intentional, not a bug.
