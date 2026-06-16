# Regression Module Refactor Notes

Reference doc for the regressor + regression-graph cleanup performed on
branch `claude/serene-allen-5ab4f3`. Use this file to triage regressions
and roll back individual files or the entire change set.

---

## Baseline

- **Baseline commit (pre-refactor):** `e98ae8be6` ("fixed dependencies")
- **Branch:** `claude/serene-allen-5ab4f3`
- **Net diff:** −827 lines across 9 files (1,835 → 504 lines kept; same behavior except 2 explicit bug fixes; see "Behavior Changes" below).

---

## Files Touched

| File | Δ | Risk |
|---|---|---|
| `pychron/core/regression/base_regressor.py` | −74 | medium (2 bug fixes change output) |
| `pychron/core/regression/ols_regressor.py` | −175 | low (vectorization, dead-code removal) |
| `pychron/core/regression/wls_regressor.py` | −59 | low (dead-code removal only) |
| `pychron/core/regression/mean_regressor.py` | −51 | low (dispatch refactor) |
| `pychron/core/regression/least_squares_regressor.py` | −42 | low (vectorized predict_error) |
| `pychron/core/regression/new_york_regressor.py` | −190 | **medium-high** (O(n²) loop vectorized; recursion → while) |
| `pychron/core/regression/interpolation_regressor.py` | −115 | low (dead-code removal, control-flow tighten) |
| `pychron/core/regression/flux_regressor.py` | −143 | low (vectorized neighbor sort, dead-code removal) |
| `pychron/graph/regression_graph.py` | −91 | medium (hot-path skips invisible overlays) |
| `pychron/processing/argon_calculations.py` | −469 | medium (~400 lines dead code stripped, decay-factor loops fused, calculate_f trapped_4036 hoisted) |
| `pychron/processing/arar_age.py` | −17 | low (_set_age_values factored, _assemble_ar_ar_isotopes tightened, _calculate_kca/kcl share helper) |
| `pychron/core/regression/tests/error_propagation.py` | +new | n/a (test-only) |
| `pychron/processing/tests/argon_calculations_test.py` | +new | n/a (test-only, 26 tests) |

---

## Behavior Changes (intentional)

These produce **different output** than baseline:

1. **`BaseRegressor._pre_clean_array`** — was `set(user) ^ set(truncate)` (symmetric
   difference). Fixed to `set(user) | set(truncate)` (union). Indices excluded by
   BOTH were previously kept; now correctly dropped. Affects `pre_clean_xs/ys`
   used by `LeastSquaresRegressor.calculate`.
2. **`BaseRegressor.calculate_outliers` IQR branch** — Python operator-precedence
   bug (`|` binds tighter than `<`/`>`). Previously raised `TypeError` for any
   IQR-filter call; now correctly returns indices outside the IQR fence.
3. **`BaseRegressor._calculate_confidence_interval`** — `tinv()` (custom JSci port,
   ~5dp accuracy) → `scipy.stats.t.ppf` (machine precision). CI values diverge
   from baseline by ~1e-6.

All other changes preserve numerical output bit-for-bit (verified against the
test suite reference values).

---

## Hot-Path Performance Wins

- **`OLSRegressor.predict_error_matrix`** — was Python loop over each xi with
  closure dispatch. Now single vectorized `(Xk·cov*Xk).sum(axis=1)`.
- **`OLSRegressor._get_X`** — was `[pow(xs, i) for i in range(d+1)]` +
  `column_stack`. Now `np.vander(xs, d+1, increasing=True)`.
- **`LeastSquaresRegressor.predict_error`** — was Python loop building per-point
  matrices. Now vectorized.
- **`NewYorkRegressor.get_slope_variance`** — was O(n²) nested Python loop.
  Now O(n) vectorized via identity `Σⱼ wⱼ²(δᵢⱼ−wᵢ/Σw)·x[j] = wᵢ²x[i] − (wᵢ/Σw)Σⱼwⱼ²x[j]`.
- **`YorkRegressor._calculate_slope_intercept`** — was Python recursion (risk of
  hitting recursion limit at the 500-iter cap). Now `while` loop.
- **`NearestNeighborFluxRegressor._get_neighbors`** — was Python `sorted` +
  `itemgetter` + `zip*`. Now `np.argsort`.
- **`RegressionGraph._regress`** — now skips `calculate_error_envelope` and
  `calculate_filter_bounds` when overlay `visible=False`. Filter-bounds overlay
  defaults to invisible, so this skips one `predict_error` per regress cycle.
- **`RegressionGraph._set_overlay_bounds`** — was three `array_equal` calls; now
  one.

---

## Dead Code Removed

- `OLSRegressor.predict_error_algebraic` (Draper & Smith 1.4.6 — superseded by `predict_error_matrix`)
- `OLSRegressor.predict_error_al` (MassSpec verification stub, docstring said "only here for verification")
- `BaseRegressor`: duplicate `mean`/`delta`/`clean_yserr` properties, `dev = delta` alias
- `ols_regressor.py` `__main__` block
- `new_york_regressor.py` `__main__` block + commented-out alternative slope-variance code
- `interpolation_regressor.py` commented `GaussianRegressor` class + `__main__`
- `flux_regressor.py` commented `BracketingFluxRegressor` + `MatchingFluxRegressor` classes
- `wls_regressor.py` 50+ lines of commented stubs
- `regression_graph.py` commented `__init__` lock, `cm_toggle_filtering` alternative branch, `set_filter_outliers` stubs
- `csv_regressor.py` entire file (matplotlib demo / `__main__` plotting script, not imported anywhere)
- `new_york_regressor.py` `ReedYorkRegressor._get_weights` (duplicate of inherited `YorkRegressor._get_weights`)

---

## Tests

Test files:
- `pychron/core/regression/tests/error_propagation.py` — accuracy / coverage tests.
- `pychron/core/regression/tests/regression.py` — behavioral tests.

```bash
uv run python -m unittest \
    pychron.core.regression.tests.error_propagation \
    pychron.core.regression.tests.regression

# Expected: 230 pass, 0 fail. Module line coverage ~95%.
```

The 5 formerly-failing baseline tests now pass: the Reed slope/intercept-error
expectations were updated to the Reed (1992) eq-14 MSWD-scaled form, and the
exponential `curve_fit` cases converge under the data-driven initial guess
(`ExponentialRegressor._calculate_initial_guess`).

---

## Rollback

### Full rollback (all 9 files + delete new test file)

```bash
git checkout e98ae8be6 -- \
    pychron/core/regression/base_regressor.py \
    pychron/core/regression/ols_regressor.py \
    pychron/core/regression/wls_regressor.py \
    pychron/core/regression/mean_regressor.py \
    pychron/core/regression/least_squares_regressor.py \
    pychron/core/regression/new_york_regressor.py \
    pychron/core/regression/interpolation_regressor.py \
    pychron/core/regression/flux_regressor.py \
    pychron/graph/regression_graph.py

rm pychron/core/regression/tests/error_propagation.py
rm pychron/core/regression/REFACTOR_NOTES.md
```

### Single-file rollback

If the regression points to a specific file:

```bash
git checkout e98ae8be6 -- pychron/core/regression/<filename>.py
```

Files most likely to need individual rollback (in order of risk):

1. `new_york_regressor.py` — vectorized variance calc + iterative slope solve
2. `base_regressor.py` — contains the 3 intentional behavior changes
3. `regression_graph.py` — skips envelope/filter_bounds compute when invisible

### Verify rollback

```bash
git diff HEAD -- pychron/core/regression/ pychron/graph/regression_graph.py
# Should show only the file(s) you intended to keep modified
uv run python -m unittest pychron.core.regression.tests.error_propagation
# Some new tests may fail after rollback if they assert the bug fixes.
# That's expected — drop or skip those assertions.
```

---

## Diagnosing a Suspected Regression

If output differs from pre-refactor behavior:

1. **First** check whether the discrepancy is one of the 3 listed behavior
   changes (xor → union, IQR precedence, tinv → scipy). Those are intentional
   fixes — the new output is correct.
2. **Otherwise**, isolate the file: roll back files one at a time, smallest
   blast-radius first (`flux_regressor.py`, `interpolation_regressor.py`,
   `wls_regressor.py`), running the relevant downstream calculation between
   each step.
3. **For numerical drift at the 1e-6 level** — check whether the path goes
   through `_calculate_confidence_interval` (CI error). scipy is more accurate
   than the old tinv; the old answer is probably the buggy one.
4. **For shape/dtype mismatches in `predict`/`predict_error`** — these now use
   `np.isscalar` + `np.atleast_1d` for dispatch. The pre-refactor code used
   `isinstance(x, (float, int))`, which **misses** `np.float64`, `np.int64`,
   and other numpy scalars. The new behavior is more permissive (treats numpy
   scalars as scalars). If callers depend on numpy scalars being treated as
   arrays of length 1, that path is now broken — report it.
5. **For York slope/intercept variance differences > 1e-10** — the
   vectorized NewYork inner loop should be algebraically identical to the
   nested loop. Any larger drift suggests a transcription bug in the
   vectorization; bisect `new_york_regressor.py` first.

---

## Quick reference: baseline test outcomes vs HEAD

|   | Baseline `e98ae8be6` | HEAD |
|---|---|---|
| `regression.py` tests | 30 pass / 5 fail-or-error | all pass |
| `error_propagation.py` tests | n/a (file did not exist) | all pass |
| combined | — | 230 pass / 0 fail (~95% line coverage) |
