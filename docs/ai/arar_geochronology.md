# Ar/Ar Geochronology — Domain Primer for Agents

This document explains the *science* Pychron exists to do, so that an agent
editing the code understands **why** a function, method, or workflow exists, not
just what it mechanically does. The other files in `docs/ai/` map code
structure; this one maps the geochronology.

If you are touching `pychron/processing`, `pychron/pipeline`,
`pychron/experiment`, `pychron/spectrometer`, or `pychron/dvc`, read this first.
For the instrument that produces the isotope data, see the companion primer
`docs/ai/noble_gas_mass_spectrometer.md`.

---

## 1. What Pychron is for

Pychron runs an **⁴⁰Ar/³⁹Ar geochronology laboratory** and reduces the data it
produces into **ages** (how long ago a rock/mineral cooled or formed) with
rigorous uncertainties. It spans the whole chain: controlling the mass
spectrometer and extraction hardware, automating the measurement sequence,
persisting raw data, and computing ages from that data.

The ⁴⁰Ar/³⁹Ar method is a variant of K–Ar dating. Potassium-40 (⁴⁰K) decays to
argon-40 (⁴⁰Ar) with a known half-life. Measure how much radiogenic ⁴⁰Ar a
sample has accumulated relative to its potassium, and you get an age. The trick
of the Ar/Ar method: instead of measuring K directly, you irradiate the sample
with neutrons to convert ³⁹K → ³⁹Ar, so a *single* noble-gas mass spectrometer
measurement of argon isotopes gives you both the parent proxy (³⁹Ar) and the
daughter (⁴⁰Ar).

---

## 2. The lab workflow (and where each stage lives)

```
 sample → irradiation → extraction → mass-spec measurement → data reduction → interpretation
```

| Stage | What happens physically | Where in code |
|-------|------------------------|---------------|
| **Irradiation** | Sample + flux monitors loaded in trays, sent to a reactor. Neutrons convert ³⁹K→³⁹Ar (and produce interfering isotopes from Ca, Cl, K). | `pychron/entry` (irradiation/level/position entry), `pychron/processing` flux handling |
| **Extraction** | Gas released from a sample by laser or furnace heating, in one step (fusion) or many (incremental/step heating). Gas is cleaned (getters) of non-noble gases. | `pychron/lasers`, `pychron/furnace`, `pychron/extraction_line`, scripted by `pychron/pyscripts` |
| **Measurement** | Cleaned argon admitted to the mass spectrometer; ion beams for masses 40,39,38,37,36 measured on detectors (Faraday cups and/or ion counters/CDD). | `pychron/spectrometer`, orchestrated by `pychron/experiment` |
| **Reduction** | Raw intensities corrected and combined into an age. (Section 4.) | `pychron/processing`, `pychron/pipeline` |
| **Persistence** | Raw + reduced data versioned in git-backed repositories. | `pychron/dvc` |
| **Interpretation** | Plateaus, isochrons, weighted means; final "interpreted age" per sample. | `pychron/processing/plateau.py`, `argon_calculations.py`, `interpreted_age.py`, `pychron/pipeline` |

An **experiment** is an automated queue of **runs**. Each run is one
extraction+measurement of one position (an unknown sample, a flux monitor, a
blank, an air shot, or a cocktail standard).

---

## 3. The measurement model (raw intensities → corrected isotopes)

Five argon isotopes are the core observables. Constant keys in
`pychron/pychron_constants.py`:

```python
ARGON_KEYS = (AR40, AR39, AR38, AR37, AR36)   # "Ar40".."Ar36"
```

| Isotope | Primary meaning in Ar/Ar |
|---------|--------------------------|
| **⁴⁰Ar** | radiogenic (from ⁴⁰K decay) + atmospheric + K-interference |
| **³⁹Ar** | proxy for K (from ³⁹K via irradiation) — the "parent" signal |
| **³⁸Ar** | Cl-derived + atmospheric + cosmogenic |
| **³⁷Ar** | proxy for Ca (from ⁴⁰Ca via irradiation); short-lived, decays |
| **³⁶Ar** | atmospheric + Ca-interference + cosmogenic — the "trapped" tracer |

Before any age math, each measured intensity is corrected for instrument and
procedural effects (see `calculate_f` docstring in `argon_calculations.py`):

- **Baseline** — detector signal with no beam (electronic zero).
- **Blank** — argon contributed by the extraction/measurement system itself,
  not the sample. Measured on blank runs, subtracted from unknowns.
- **IC factor** (inter-calibration / detector intercalibration) — relative gain
  between detectors, so ion-counter and Faraday signals are comparable.
- **Discrimination / mass fractionation** — the spectrometer favors some masses
  over others; calibrated against air shots (known atmospheric ⁴⁰/³⁶ ≈ 295.5).
- **Ar37/Ar39 decay** — ³⁷Ar (≈35 d half-life) and ³⁹Ar decay measurably
  between irradiation and analysis; corrected back to irradiation time.

Per-isotope correction logic lives in `pychron/processing/isotope.py` and
`arar_age.py`. By the time intensities reach `calculate_f`, they are assumed
**already** blank/baseline/IC/discrimination/decay corrected.

### Time zero — the intensity-vs-time intercept

A single isotope is not measured as one number. The detector records a **time
series** of intensity during the few minutes the gas is in the analyzer
(`Isotope.xs`/`ys` in `isotope.py`). In static vacuum the signal changes over
that window — radiogenic peaks decay as gas is consumed/pumped, blanks grow —
so the physically meaningful value is the signal **at the moment the gas was
admitted**: *time zero*.

Pychron fits a regression (linear/parabolic/exponential/mean per the chosen
fit) to the series and extrapolates to t=0:

- `Isotope.offset_xs = xs − time_zero_offset` shifts the clock so t=0 is the
  inlet time; `set_time_zero()` sets the offset.
- `_predict_at_t_zero()` runs the regressor and returns
  `(reg.predict(0), reg.predict_error(0))` as one `ufloat`, cached so every
  access shares the same correlation node.
- That intercept value/error is what feeds blank/baseline/IC correction and
  ultimately `calculate_f`.

The choice of fit type and time-zero offset directly changes the reported
intensity, hence the age. This is intentional extrapolation, not curve-cleaning.

---

## 4. The reduction math (corrected isotopes → age)

This is the scientific heart of the codebase:
`pychron/processing/argon_calculations.py`. The pipeline, in order:

1. **Interference corrections** — `interference_corrections()`
   Neutron irradiation produces argon not just from K but also from Ca, Cl, and
   K itself, using reactor-specific **production ratios** (e.g. `Ca3937`,
   `K3739`, `Ca3637`, `K4039`). This step partitions the measured ³⁹/³⁷/³⁸/³⁶
   into K-derived, Ca-derived, etc. `K3739` may be solved normally or fixed
   (`apply_fixed_k3739`).

2. **Atmospheric correction** — `calculate_atmospheric()`
   Separates atmospheric (trapped) argon and Cl-derived argon from ³⁶/³⁸ using
   the air ³⁸/³⁶ ratio and ³⁶Cl decay (McDougall & Harrison; Roddick 1983;
   Foland 1993). Yields `atm36`, `cl36`, etc.

3. **Cosmogenic correction** (optional) — `calculate_cosmogenic_components()`
   Two-component mixing to remove cosmic-ray-produced ³⁶/³⁸ in old/exposed
   samples.

4. **F = ⁴⁰Ar\*/³⁹Ar_K** — `calculate_f()`
   `rad40 = a40 − atm40 − k40`, then `F = rad40 / k39`. `F` (a.k.a. `F`/`Far`)
   is the radiogenic-⁴⁰/³⁹_K ratio — the age-bearing quantity. The function
   also returns `f_wo_irrad` (F with irradiation-ratio errors zeroed, for error
   budgeting) and `radiogenic_yield` (% radiogenic ⁴⁰Ar).

5. **Age** — `age_equation()`
   ```
   age = (1/λ_total) · ln(1 + J·F)
   ```
   `J` is the **irradiation parameter** (the neutron-fluence calibration, see
   §6). `λ_total` is the total ⁴⁰K decay constant. Age comes out in years and is
   scaled to the configured units (`scale_age`).

Supporting calculations:
- `calculate_flux()` — inverts the age equation to solve for `J` from a flux
  monitor of known age.
- `convert_age()` / `age_converter.py` — recompute legacy ages onto new monitor
  ages or decay constants.
- Plateau, isochron, ideogram, and error propagation are covered in §5.

---

## 5. Interpretation & statistics (many runs → one age)

A single run gives one F/age. Real results combine many steps (step-heating) or
many aliquots (single-fusion) into one defensible age with uncertainty. The
combining methods live in `pychron/processing` (math) and
`pychron/pipeline/plot/plotter` (figures).

### Isochron — `argon_calculations.py`

`calculate_isochron()` / `get_isochron_regressors()`. The **inverse isochron**
plots ³⁶Ar/⁴⁰Ar (y) vs ³⁹Ar/⁴⁰Ar (x) across steps/aliquots:

- The **x-intercept** relates to age (`r = 1/regx.intercept`, fed to
  `age_equation`); the **y-intercept** gives the trapped ⁴⁰Ar/³⁶Ar.
- Unlike a plateau, the isochron **solves for the trapped composition** instead
  of assuming air (295.5), so it detects/handles excess or non-atmospheric
  trapped argon.
- Regression is error-weighted in both axes (correlated x/y errors): York-type
  fits in `pychron/core/regression/new_york_regressor.py` —
  `NewYorkRegressor` (default), `YorkRegressor`, `ReedYorkRegressor`. Selected
  by the `reg=` argument.
- `include_j_err` toggles whether J uncertainty enters the isochron age.

### Plateau — `argon_calculations.py` + `plateau.py`

`calculate_plateau_age()` builds a `Plateau` over the **age spectrum** (age vs
cumulative ³⁹Ar released, step by step). A valid plateau is a run of contiguous
steps that:

- agree within error (`overlap_sigma`, default 2σ; method `FLECK` etc.),
- span ≥ a minimum number of steps (`nsteps`, default 3), and
- release ≥ a minimum gas fraction (`gas_fraction`, default 50% of ³⁹Ar).

`find_plateaus(method)` locates the qualifying steps (or `fixed_steps` forces
them); the plateau age is the **weighted mean** of those steps —
inverse-variance by default, or ³⁹ArK-volume-weighted (`kind="vol_fraction"`).
A flat plateau implies the sample behaved as a closed system; a disturbed
spectrum (rising/saddle) signals argon loss or excess argon.

### Ideogram — `pychron/pipeline/plot/plotter/ideogram.py`

A probability-density figure of a population of ages (`Ideogram(BaseArArFigure)`).
Each age is a Gaussian (center = age, width = its error); summing them shows
where ages cluster:

- `cumulative_probability` (sum of Gaussians) and `kernel_density` (KDE) from
  `pychron/core/stats/probability_curves.py` build the curve
  (`_plot_relative_probability`).
- Used to judge whether a sample is a single age population or a mix
  (multiple peaks), and to read a weighted-mean/mode age for the group.
- Distinct from the age **spectrum** (plateau): an ideogram ignores gas
  fraction and step order; it is purely about the distribution of ages.

### Error propagation

Pychron carries uncertainties two complementary ways:

- **Automatic** — the `uncertainties` package (`ufloat`) propagates errors and
  inter-variable **correlations** through every operation. Preserve `tag=`
  arguments: they label error components so `error_contrib.py` can report each
  source's contribution to the final age error. Stripping a value to
  `nominal_value` mid-chain silently drops its error and its correlations.
- **Analytic** — closed-form formulas where they matter, e.g.
  `calculate_error_F` and `calculate_error_t` (McDougall & Harrison eq. 3.43)
  for the F and age errors.

`error_calc_kind` / `error_type` select how regression and mean errors are
computed (e.g. SE vs SD, MSWD-scaled). **MSWD** (mean square weighted deviation)
gauges scatter vs analytical error: ≈1 means errors explain the scatter; ≫1
means geological scatter and the reported error is inflated accordingly.

---

## 6. Key concepts → glossary

- **J / J-value (irradiation parameter)** — converts measured ⁴⁰Ar\*/³⁹Ar_K (F)
  into age. Determined by co-irradiating **flux monitors** (mineral standards of
  independently-known age, e.g. Fish Canyon sanidine) and solving the age
  equation for J. Each sample's J is interpolated from monitors around it.
  See `calculate_flux`, `pychron/processing/flux.py`, `j_error_mixin.py`.
- **Flux monitor / standard** — a sample of known age used to measure neutron
  fluence (J). "Unknowns" are the samples whose ages you actually want.
- **F (Far)** — radiogenic ⁴⁰Ar\* / ³⁹Ar_K. The age-bearing ratio.
- **Radiogenic ⁴⁰Ar (rad40 / ⁴⁰Ar\*)** — the ⁴⁰Ar from in-situ ⁴⁰K decay, after
  removing atmospheric and interference ⁴⁰Ar.
- **Trapped / atmospheric argon** — non-radiogenic ⁴⁰Ar; assumed air-like
  (⁴⁰/³⁶ ≈ 295.5) unless an isochron says otherwise.
- **Production ratios / interference corrections** — reactor-specific factors
  (`Ca3937`, `K3739`, `Ca3637`, `Ca3837`, `K4039`, `K3839`, `Cl3638`) describing
  unwanted argon made during irradiation.
- **Plateau** — in step-heating, a run of consecutive steps with concordant ages
  releasing a large fraction of the ³⁹Ar; their weighted mean is the plateau age
  (§5).
- **Isochron** — regression across steps/aliquots that solves for age *and*
  trapped composition simultaneously (§5).
- **Ideogram** — probability-density plot of an age population; reveals single vs
  mixed populations (§5).
- **MSWD** — mean square weighted deviation; scatter relative to analytical
  error (≈1 good, ≫1 = geological scatter).
- **Step heating vs total fusion** — incremental temperature steps (resolves age
  spectra/disturbance) vs a single melt (one bulk age).
- **Blank / baseline / air shot / cocktail** — procedural runs: system
  background, detector zero, atmospheric-ratio calibration, multi-element check.
- **KCa / KCl** — K/Ca and K/Cl ratios derived from ³⁹/³⁷ and ³⁸/³⁹; chemical
  fingerprints reported alongside age (`_calculate_kca`, `_calculate_kcl`).
- **MDD** — multiple-diffusion-domain thermal modeling (`pychron/mdd`); thermal
  history from age spectra.
- **Interpreted age** — the lab's final adopted age for a sample (plateau,
  isochron, weighted mean, or integrated), `interpreted_age.py`.

---

## 7. Constants reference

Decay/physical constants — `pychron/processing/arar_constants.py` (`ArArConstants`):

- `lambda_e` — ⁴⁰K electron-capture branch → ⁴⁰Ar (the geochronologically useful
  branch). Default `5.81e-11 /yr`.
- `lambda_b` — ⁴⁰K beta branch → ⁴⁰Ca. Default `4.962e-10 /yr`.
- `lambda_k` — total ⁴⁰K decay constant (`λ_e + λ_b`), used in the age equation.
- `lambda_Ar37`, `lambda_Ar39`, `lambda_Cl36` — decay of the irradiation-produced
  short-lived isotopes.
- `atm4036` (≈ 295.5, Nier 1950) and `atm3836` — atmospheric argon ratios.
- `solar3836`, `cosmo3836` — end-member ³⁸/³⁶ for cosmogenic correction.

`FLUX_CONSTANTS` and `K_DECAY_CONSTANTS` in `pychron/pychron_constants.py` hold
named decay-constant sets (e.g. Min 2008, Steiger & Jäger 1977). Different labs
and papers adopt different constants; **never silently change a default** — the
choice changes every reported age. Citation fields (`*_citation`) record the
source.

---

## 8. Pitfalls for an editing agent

- Ages and ratios carry uncertainties via `ufloat`; don't strip `nominal_value`
  off a value that feeds an error budget, and preserve `tag=`.
- The correction order in §4 is not arbitrary — interference before atmospheric
  before cosmogenic before F. Reordering changes results.
- Decay constants, monitor ages, and production ratios are *configuration*, not
  code constants; defaults exist but real runs load them per-irradiation/lab.
- `f_wo_irrad`, `*_wo_*` variants exist to isolate error sources — they are not
  redundant copies.
- Negative corrected quantities can be physically meaningless but statistically
  valid; respect flags like `allow_negative_ca_correction`.
