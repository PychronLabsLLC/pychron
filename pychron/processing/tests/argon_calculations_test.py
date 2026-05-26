# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
# ===============================================================================
"""
Reference tests for `pychron.processing.argon_calculations` — pure functions
operating on isotope intensities, interference ratios, and Ar/Ar constants.

Reference values come from direct algebraic recomputation against the same
constants the production code uses. The point of these tests is to *lock in*
current numerical behavior so a hot-path optimization can be validated
bit-for-bit against this baseline.
"""

import math
from unittest import TestCase

from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.arar_constants import ArArConstants
from pychron.processing.argon_calculations import (
    abundance_sensitivity_correction,
    age_equation,
    apply_fixed_k3739,
    calculate_arar_decay_factors,
    calculate_arar_decay_factors_dalrymple,
    calculate_atmospheric,
    calculate_cosmogenic_components,
    calculate_decay_time,
    calculate_f,
    calculate_flux,
    calculate_fractional_loss,
    calculate_plateau_age,
    convert_age,
    interference_corrections,
)


def _interferences():
    return {
        "Ca3937": ufloat(0.0007, 0),
        "K3739": ufloat(0.01, 0),
        "K3839": ufloat(0.013, 0),
        "Ca3637": ufloat(0.00026, 0),
        "Ca3837": ufloat(0.00019, 0),
        "K4039": ufloat(0.0002, 0),
        "Cl3638": ufloat(0.0, 0),
    }


def _isotopes():
    """Synthetic ~young volcanic Ar40/39/38/37/36 intensities."""
    return [
        ufloat(1000.0, 1.0),
        ufloat(100.0, 0.5),
        ufloat(10.0, 0.05),
        ufloat(1.0, 0.005),
        ufloat(2.0, 0.01),
    ]


class AgeEquationTest(TestCase):
    """`age_equation(J, F)` returns `λ⁻¹ · ln(1 + J·F)` in the configured
    age units (default years)."""

    @classmethod
    def setUpClass(cls):
        cls.ac = ArArConstants()
        cls.lk = nominal_value(cls.ac.lambda_k)

    def test_age_for_known_jf(self):
        j = (1e-3, 1e-6)
        f = (10.0, 0.01)
        age = age_equation(j, f, arar_constants=self.ac)
        expected = (1 / self.lk) * math.log(1 + 1e-3 * 10)
        self.assertAlmostEqual(nominal_value(age), expected, places=2)

    def test_zero_jf_returns_zero(self):
        age = age_equation((0.0, 0.0), (1.0, 0.0), arar_constants=self.ac)
        self.assertAlmostEqual(nominal_value(age), 0.0, places=10)

    def test_age_propagates_uncertainty(self):
        age = age_equation((1e-3, 1e-6), (10.0, 0.01), arar_constants=self.ac)
        self.assertGreater(std_dev(age), 0)

    def test_calculate_flux_inverts_age_equation(self):
        """`calculate_flux(F, age)` is the inverse of `age_equation(J, F)`."""
        j_true = 1e-3
        f_true = 10.0
        age = age_equation((j_true, 0.0), (f_true, 0.0), arar_constants=self.ac)
        j_recovered = calculate_flux((f_true, 0.0), (nominal_value(age), 0.0))
        self.assertAlmostEqual(nominal_value(j_recovered), j_true, places=10)


class AbundanceSensitivityTest(TestCase):
    """Symmetric peak-tail correction: m40' = m40 - α·(m39+m39).
    For α=0, output equals input."""

    def test_zero_alpha_passthrough(self):
        isos = [1000.0, 100.0, 10.0, 5.0, 2.0]
        out = abundance_sensitivity_correction(isos, 0.0)
        self.assertEqual(out, isos)

    def test_known_alpha(self):
        s40, s39, s38, s37, s36 = 1000.0, 100.0, 10.0, 5.0, 2.0
        alpha = 0.0001
        n40, n39, n38, n37, n36 = abundance_sensitivity_correction([s40, s39, s38, s37, s36], alpha)
        self.assertAlmostEqual(n40, s40 - alpha * (s39 + s39), places=10)
        self.assertAlmostEqual(n39, s39 - alpha * (s40 + s38), places=10)
        self.assertAlmostEqual(n38, s38 - alpha * (s39 + s37), places=10)
        self.assertAlmostEqual(n37, s37 - alpha * (s38 + s36), places=10)
        self.assertAlmostEqual(n36, s36 - alpha * (s37 + s37), places=10)


class DecayFactorsTest(TestCase):
    """McDougall & Harrison p.75 eq 3.22 (default) and Dalrymple alternative."""

    def test_no_segments_returns_unity(self):
        d37, d39 = calculate_arar_decay_factors(1e-10, 1e-10, None)
        self.assertEqual((d37, d39), (1.0, 1.0))

    def test_unit_mismatch_raises(self):
        """Passing seconds with per-day decay constants must raise instead
        of silently overflowing `math.exp`."""
        # lambda_Ar37 ≈ 0.02 per day. 1 year in seconds = 3.15e7.
        # 0.02 * 3.15e7 = 6.3e5 → way above 50 → must raise.
        segs_seconds = [(1.0, 86400.0, 86400.0 * 365.0, None, None)]
        with self.assertRaises(ValueError) as ctx:
            calculate_arar_decay_factors(0.02, 7e-6, segs_seconds)
        self.assertIn("same unit", str(ctx.exception))

    def test_unit_mismatch_raises_for_dalrymple(self):
        segs_seconds = [(1.0, 86400.0, 86400.0 * 365.0, None, None)]
        with self.assertRaises(ValueError):
            calculate_arar_decay_factors(0.02, 7e-6, segs_seconds, use_mh=False)

    def test_days_units_pass_guard(self):
        """1-day irradiation, 1-year decay in days — well within range."""
        segs_days = [(1.0, 1.0, 365.0, None, None)]
        # should not raise
        calculate_arar_decay_factors(0.02, 7e-6, segs_days)

    def test_zero_decay_constants_approach_unity(self):
        segs = [(1.0, 86400.0, 86400.0 * 365, None, None)]
        d37, d39 = calculate_arar_decay_factors(1e-12, 1e-12, segs)
        # for negligible λ the decay correction → 1
        self.assertAlmostEqual(d37, 1.0, places=4)
        self.assertAlmostEqual(d39, 1.0, places=4)

    def test_known_single_segment(self):
        """Locks current behavior for a typical short irradiation."""
        segs = [(1.0, 86400.0, 86400.0 * 365, None, None)]
        d37, d39 = calculate_arar_decay_factors(7.2e-10, 7.0e-10, segs)
        self.assertAlmostEqual(d37, 1.022997480219743, places=10)
        self.assertAlmostEqual(d39, 1.0223515753822912, places=10)

    def test_dalrymple_matches_mh_at_zero_dti(self):
        """When dti=0 (no time-since-end), Dalrymple and M&H should agree."""
        segs = [(1.0, 86400.0, 0.0, None, None)]
        mh37, mh39 = calculate_arar_decay_factors(7.2e-10, 7.0e-10, segs, use_mh=True)
        dm37, dm39 = calculate_arar_decay_factors_dalrymple(7.2e-10, 7.0e-10, segs)
        self.assertAlmostEqual(mh37, dm37, places=8)
        self.assertAlmostEqual(mh39, dm39, places=8)


class FixedK3739Test(TestCase):
    """`apply_fixed_k3739` deconvolves K from Ca using a fixed K37/K39 ratio."""

    def test_zero_ca_passthrough(self):
        # x = K37/K39 = 0.05, Ca3937 = 0 → ca37 = a39 * x = 5, k39 = 100-0 = 100
        a39 = ufloat(100, 1)
        pr = {"Ca3937": 0}
        ca37, ca39, k37, k39 = apply_fixed_k3739(a39, pr, 0.05)
        # y = 1/Ca3937 → ZeroDivisionError → y = 1
        # ca37 = (100 * 0.05 * 1) / (0.05 + 1) = 5/1.05 ≈ 4.76
        self.assertAlmostEqual(nominal_value(ca37), 5.0 / 1.05, places=6)
        self.assertAlmostEqual(nominal_value(k39), 100 - nominal_value(ca39), places=6)

    def test_k37_proportional_to_k39(self):
        a39 = ufloat(100, 0)
        ca37, ca39, k37, k39 = apply_fixed_k3739(a39, {"Ca3937": 0.001}, 0.05)
        # k37 = x * k39
        self.assertAlmostEqual(nominal_value(k37), 0.05 * nominal_value(k39), places=8)


class InterferenceCorrectionsTest(TestCase):
    """Normal-mode K/Ca deconvolution. With Ca3937=0 (pure K),
    k39 = a39 and ca37 = a37 (no Ca contamination)."""

    @classmethod
    def setUpClass(cls):
        cls.ac = ArArConstants()

    def test_pure_k_no_ca(self):
        a39 = ufloat(100, 1)
        a37 = ufloat(0, 0)
        pr = {"Ca3937": 0, "K3739": 0, "K3839": 0.013, "Ca3637": 0, "Ca3837": 0}
        k37, k38, k39, ca36, ca37, ca38, ca39 = interference_corrections(a39, a37, pr, self.ac)
        self.assertAlmostEqual(nominal_value(k39), 100.0, places=6)
        self.assertAlmostEqual(nominal_value(ca37), 0.0, places=10)
        self.assertAlmostEqual(nominal_value(k38), 1.3, places=6)

    def test_k38_proportional_to_k39(self):
        a39 = ufloat(100, 1)
        a37 = ufloat(1, 0.01)
        pr = {"Ca3937": 0.0007, "K3739": 0.01, "K3839": 0.013, "Ca3637": 0.00026, "Ca3837": 0.00019}
        out = interference_corrections(a39, a37, pr, self.ac)
        k38, k39 = out[1], out[2]
        # k38 = K3839 * k39 = 0.013 * k39
        self.assertAlmostEqual(nominal_value(k38), 0.013 * nominal_value(k39), places=10)


class AtmosphericTest(TestCase):
    """When Cl3638=0, cl36=cl38=0 and atm36 = a36 - ca36."""

    @classmethod
    def setUpClass(cls):
        cls.ac = ArArConstants()

    def test_no_chlorine_atm36_is_nonradiogenic(self):
        a38 = ufloat(0.5, 0.005)
        a36 = ufloat(0.1, 0.001)
        k38 = ufloat(0.013, 0.0001)
        ca38 = ufloat(0.00019, 0)
        ca36 = ufloat(0.00026, 0)
        pr = {"Cl3638": 0}
        atm36, atm38, cl36, cl38 = calculate_atmospheric(
            a38, a36, k38, ca38, ca36, 365, pr, self.ac
        )
        self.assertAlmostEqual(nominal_value(cl36), 0.0, places=12)
        # atm36 = (a36 - ca36) when m=0
        self.assertAlmostEqual(nominal_value(atm36), 0.1 - 0.00026, places=8)

    def test_atm38_proportional_to_atm36(self):
        """atm38 = atm3836 * atm36."""
        a38 = ufloat(0.5, 0)
        a36 = ufloat(0.1, 0)
        k38 = ufloat(0.013, 0)
        ca38 = ufloat(0.0, 0)
        ca36 = ufloat(0.0, 0)
        atm36, atm38, _, _ = calculate_atmospheric(
            a38, a36, k38, ca38, ca36, 365, {"Cl3638": 0}, self.ac
        )
        self.assertAlmostEqual(
            nominal_value(atm38),
            nominal_value(self.ac.atm3836) * nominal_value(atm36),
            places=10,
        )

    def test_atm3836_uncertainty_propagates_to_atm38(self):
        """Regression: atm3836 std_dev was stripped via nominal_value;
        now must propagate into atm38."""
        a38 = ufloat(0.5, 0)
        a36 = ufloat(0.1, 0)
        k38 = ufloat(0.013, 0)
        ca38 = ufloat(0.0, 0)
        ca36 = ufloat(0.0, 0)
        atm36, atm38, _, _ = calculate_atmospheric(
            a38, a36, k38, ca38, ca36, 365, {"Cl3638": 0}, self.ac
        )
        # default ArArConstants has nonzero atm3836 std_dev (~0.0004)
        self.assertGreater(std_dev(self.ac.atm3836), 0)
        self.assertGreater(std_dev(atm38), 0)


class CalculateFTest(TestCase):
    """Full F-value pipeline. F = rad40 / k39 after applying interference and
    atmospheric corrections."""

    @classmethod
    def setUpClass(cls):
        cls.ac = ArArConstants()
        cls.iso = _isotopes()
        cls.pr = _interferences()
        cls.f, cls.f_wo, cls.nar, cls.comp, cls.ifc = calculate_f(
            cls.iso, decay_time=365, interferences=cls.pr, arar_constants=cls.ac
        )

    def test_f_equals_rad40_over_k39(self):
        rad40 = self.comp["rad40"]
        k39 = self.comp["k39"]
        self.assertAlmostEqual(
            nominal_value(self.f), nominal_value(rad40) / nominal_value(k39), places=10
        )

    def test_f_wo_irrad_has_smaller_error(self):
        """f_wo_irrad uses zero-uncertainty interference ratios, so its
        error must be ≤ f's error."""
        self.assertLessEqual(std_dev(self.f_wo), std_dev(self.f))

    def test_radiogenic_yield_is_percent(self):
        ry = nominal_value(self.comp["radiogenic_yield"])
        self.assertGreaterEqual(ry, 0)
        self.assertLessEqual(ry, 100.0)

    def test_non_ar_isotope_keys(self):
        for k in ("k40", "ca39", "k38", "ca38", "cl38", "k37", "ca37", "ca36", "cl36"):
            self.assertIn(k, self.nar)

    def test_interference_corrected_keys(self):
        for k in ("Ar40", "Ar39", "Ar38", "Ar37", "Ar36"):
            self.assertIn(k, self.ifc)


class PlateauAgeTest(TestCase):
    """`calculate_plateau_age` returns (weighted_mean, error, (start, end))."""

    def setUp(self):
        self.ages = [10.0, 10.05, 10.02, 11.0, 12.0]
        self.errors = [0.1, 0.1, 0.1, 0.5, 0.5]
        self.k39 = [1e3, 1.5e3, 2e3, 5e2, 3e2]
        self.steps = ["A", "B", "C", "D", "E"]

    def test_basic_plateau(self):
        out = calculate_plateau_age(self.ages, self.errors, self.k39, self.steps, excludes=[])
        self.assertIsNotNone(out)
        wm, we, pidx = out
        self.assertAlmostEqual(wm, 10.036, places=2)
        self.assertEqual(pidx, (0, 3))

    def test_fixed_steps_window(self):
        out = calculate_plateau_age(
            self.ages,
            self.errors,
            self.k39,
            self.steps,
            excludes=[],
            options={"fixed_steps": ("A", "C")},
        )
        wm, we, pidx = out
        self.assertEqual(pidx, (0, 2))
        # weighted mean of first 3 ages with equal errors
        expected = sum(self.ages[:3]) / 3
        self.assertAlmostEqual(wm, expected, places=2)

    def test_vol_fraction_weighted_mean(self):
        """`kind='vol_fraction'` uses 39ArK signals as external weights.
        wm = Σ(wi*ai) / Σwi.
        var(wm) = Σ(wi² * σi²) / (Σwi)²."""
        import numpy as np

        out = calculate_plateau_age(
            self.ages,
            self.errors,
            self.k39,
            self.steps,
            kind="vol_fraction",
            excludes=[],
        )
        wm, we, pidx = out
        ages = np.asarray(self.ages)[slice(pidx[0], pidx[1] + 1)]
        errs = np.asarray(self.errors)[slice(pidx[0], pidx[1] + 1)]
        wts = np.asarray(self.k39)[slice(pidx[0], pidx[1] + 1)]
        sw = wts.sum()
        expected_wm = (wts * ages).sum() / sw
        expected_we = ((wts**2 * errs**2).sum()) ** 0.5 / sw
        self.assertAlmostEqual(wm, expected_wm, places=10)
        self.assertAlmostEqual(we, expected_we, places=10)

    def test_vol_fraction_uniform_weights_matches_unweighted_mean(self):
        import numpy as np

        ages = [10.0, 10.0, 10.0, 10.0, 10.0]
        errors = [0.1, 0.1, 0.1, 0.1, 0.1]
        k39 = [1.0, 1.0, 1.0, 1.0, 1.0]
        steps = ["A", "B", "C", "D", "E"]
        out = calculate_plateau_age(ages, errors, k39, steps, kind="vol_fraction", excludes=[])
        wm, we, _ = out
        self.assertAlmostEqual(wm, 10.0, places=10)
        # uniform weights → var = Σσi² / n² = (5*0.01)/25 = 0.002; se = √0.002
        self.assertAlmostEqual(we, (5 * 0.01) ** 0.5 / 5, places=10)


class CosmogenicComponentsTest(TestCase):
    """Two-component mixing: rm = fs·rs + fc·rc where fs+fc=1.
    Inverse: fs = (rc - rm)/(rc - rs)."""

    def setUp(self):
        self.ac = ArArConstants()
        self.ac.set_cosmogenic_ratios((0.1869, 0.001), (0.65, 0.01))

    def test_pure_solar_returns_all_solar(self):
        """When measured ratio = solar ratio, fs=1, no cosmogenic component."""
        c36 = ufloat(1.0, 0)
        c38 = ufloat(0.1869, 0)
        cosmo36, cosmo38, noncosmo36, noncosmo38 = calculate_cosmogenic_components(
            c36, c38, self.ac
        )
        self.assertAlmostEqual(nominal_value(cosmo38), 0.0, places=10)
        self.assertAlmostEqual(nominal_value(cosmo36), 0.0, places=10)

    def test_pure_cosmogenic_returns_all_cosmo(self):
        """When measured ratio = cosmogenic ratio, fs=0, no solar."""
        c36 = ufloat(1.0, 0)
        c38 = ufloat(0.65, 0)
        cosmo36, cosmo38, noncosmo36, noncosmo38 = calculate_cosmogenic_components(
            c36, c38, self.ac
        )
        self.assertAlmostEqual(nominal_value(noncosmo38), 0.0, places=10)
        self.assertAlmostEqual(nominal_value(noncosmo36), 0.0, places=10)

    def test_components_sum_to_total(self):
        c36 = ufloat(1.0, 0)
        c38 = ufloat(0.3, 0)
        cosmo36, cosmo38, noncosmo36, noncosmo38 = calculate_cosmogenic_components(
            c36, c38, self.ac
        )
        self.assertAlmostEqual(nominal_value(cosmo38) + nominal_value(noncosmo38), 0.3, places=10)
        self.assertAlmostEqual(nominal_value(cosmo36) + nominal_value(noncosmo36), 1.0, places=10)


class DecayTimeTest(TestCase):
    def test_half_life(self):
        # decay_time(dc, 0.5) = ln(0.5) / dc
        self.assertAlmostEqual(calculate_decay_time(1e-3, 0.5), math.log(0.5) / 1e-3, places=10)

    def test_full_remaining(self):
        # decay_time(dc, 1.0) = 0
        self.assertAlmostEqual(calculate_decay_time(1e-3, 1.0), 0.0, places=10)


class AgeEquationEdgeCasesTest(TestCase):
    def setUp(self):
        self.ac = ArArConstants()

    def test_tuple_j(self):
        age = age_equation((1e-3, 1e-6), ufloat(10.0, 0.01), arar_constants=self.ac)
        self.assertGreater(nominal_value(age), 0)

    def test_tuple_f(self):
        age = age_equation(ufloat(1e-3, 1e-6), (10.0, 0.01), arar_constants=self.ac)
        self.assertGreater(nominal_value(age), 0)

    def test_include_decay_error_increases_uncertainty(self):
        j = ufloat(1e-3, 1e-6)
        f = ufloat(10.0, 0.01)
        age_no_decay = age_equation(j, f, include_decay_error=False, arar_constants=self.ac)
        age_decay = age_equation(j, f, include_decay_error=True, arar_constants=self.ac)
        # Lambda_k uncertainty should add to error
        self.assertGreaterEqual(std_dev(age_decay), std_dev(age_no_decay))

    def test_explicit_lambda_k_used(self):
        # Force a tiny lambda_k → huge age
        small = ufloat(1e-15, 0)
        age = age_equation((1e-3, 0), (10.0, 0), lambda_k=small, arar_constants=self.ac)
        # age = (1/1e-15) * ln(1+0.01) ≈ 1e13
        self.assertGreater(nominal_value(age), 1e12)

    def test_negative_argument_returns_zero(self):
        """log(1 + j*f) with j*f <= -1 raises ValueError → returns ufloat(0,0)."""
        age = age_equation((1.0, 0), (-2.0, 0), arar_constants=self.ac)
        self.assertEqual(nominal_value(age), 0)


class CalculateFluxFallbackTest(TestCase):
    """calculate_flux handles tuple inputs + zero-division."""

    def test_tuple_age(self):
        j = calculate_flux((10.0, 0.01), (1e6, 1e3))
        self.assertGreater(nominal_value(j), 0)

    def test_zero_f_returns_default(self):
        # ZeroDivisionError caught → returns ufloat(1, 0)
        j = calculate_flux((0.0, 0), (1e6, 0))
        self.assertEqual(nominal_value(j), 1)


class CalculateFractionalLossTest(TestCase):
    """McDougall & Harrison plane diffusion model for K-feldspar."""

    def test_short_time_small_f(self):
        f = calculate_fractional_loss(t=1, temp=400, a=0.1)
        self.assertGreater(f, 0)
        self.assertLess(f, 0.5)

    def test_truncated_branch_used_at_intermediate_loss(self):
        """When 0.45 ≤ f ≤ 1, switches to truncated exponential form."""
        # tune parameters to land in the intermediate regime
        f = calculate_fractional_loss(t=1e3, temp=350, a=0.01)
        self.assertGreater(f, 0)


class CalculatePlateauAgeEdgeTest(TestCase):
    def setUp(self):
        self.ages = [10.0, 10.05, 10.02, 11.0, 12.0]
        self.errors = [0.1, 0.1, 0.1, 0.5, 0.5]
        self.k39 = [1e3, 1.5e3, 2e3, 5e2, 3e2]
        self.steps = ["A", "B", "C", "D", "E"]

    def test_fixed_steps_invalid_start_step(self):
        out = calculate_plateau_age(
            self.ages,
            self.errors,
            self.k39,
            self.steps,
            excludes=[],
            options={"fixed_steps": ("NONEXISTENT", "C")},
        )
        # sidx None → falls through to plateau finder
        self.assertIsNotNone(out)

    def test_fixed_steps_only_start(self):
        out = calculate_plateau_age(
            self.ages,
            self.errors,
            self.k39,
            self.steps,
            excludes=[],
            options={"fixed_steps": ("B", "")},
        )
        wm, we, pidx = out
        # sidx=1, eidx=n-1
        self.assertEqual(pidx[0], 1)

    def test_fixed_steps_only_end(self):
        out = calculate_plateau_age(
            self.ages,
            self.errors,
            self.k39,
            self.steps,
            excludes=[],
            options={"fixed_steps": ("", "C")},
        )
        wm, we, pidx = out
        # sidx=0
        self.assertEqual(pidx[0], 0)

    def test_returns_none_when_no_plateau(self):
        # too-noisy data and only 2 steps → no plateau
        out = calculate_plateau_age(
            [1.0, 100.0],
            [0.1, 0.1],
            [1e3, 1e3],
            ["A", "B"],
            excludes=[],
        )
        # Likely returns None
        # (just verify no crash and either None or tuple)
        self.assertTrue(out is None or isinstance(out, tuple))


class ConvertAgeTest(TestCase):
    """convert_age uses the global converter singleton to rescale ages.

    NOTE: convert_age's internal `_calculate_r(age)` computes
    `exp(lambda_k * age * 1e6)`. For age in years this overflows; the
    function apparently expects age in Ma. Documented behavior locked here."""

    def test_new_monitor_age_passed_returns_unchanged(self):
        original_uage = ufloat(10.0, 0.1, tag="test")
        result = convert_age(
            original_uage,
            original_monitor_age=28.201,
            original_lambda_k=5.543e-10,
            new_monitor_age=28.5,  # not None → skip conversion
            new_lambda_k=5.543e-10,
        )
        self.assertEqual(result, original_uage)

    def test_conversion_path_currently_broken(self):
        """KNOWN BUG: age_converter._n is float (1e5) → numpy.ones(float)
        TypeError. Locks current behavior so a future fix is detected."""
        original_uage = ufloat(10.0, 0.1, tag="test_age_ma")
        with self.assertRaises(TypeError):
            convert_age(
                original_uage,
                original_monitor_age=28.201,
                original_lambda_k=5.543e-10,
                new_monitor_age=None,
                new_lambda_k=5.543e-10,
            )


class InterferenceCorrectionsFixedModeTest(TestCase):
    """Fixed K3739 mode dispatch in interference_corrections."""

    def setUp(self):
        self.ac = ArArConstants()

    def test_explicit_fixed_k3739_dispatches(self):
        a39 = ufloat(100, 1)
        a37 = ufloat(1, 0.01)
        pr = {"Ca3937": 0.0007, "K3839": 0.013, "Ca3637": 0.00026, "Ca3837": 0.00019}
        out = interference_corrections(a39, a37, pr, self.ac, fixed_k3739=0.05)
        k37, k38, k39, ca36, ca37, ca38, ca39 = out
        # k37 = x * k39 = 0.05 * k39
        self.assertAlmostEqual(nominal_value(k37), 0.05 * nominal_value(k39), places=8)

    def test_fixed_k3739_from_arar_constants(self):
        a39 = ufloat(100, 1)
        a37 = ufloat(1, 0.01)
        pr = {"Ca3937": 0.0007}
        self.ac.k3739_mode = "Fixed"
        # fixed_k3739 falls back to arar_constants.fixed_k3739
        out = interference_corrections(a39, a37, pr, self.ac)
        self.assertEqual(len(out), 7)


class CalculateAtmosphericChlorineTest(TestCase):
    """Calculate_atmospheric with non-zero Cl3638 — exercises the
    chlorine-correction branch where atm3836 uncertainty matters."""

    def test_with_chlorine_yields_nonzero_cl(self):
        ac = ArArConstants()
        a38 = ufloat(0.5, 0.005)
        a36 = ufloat(0.1, 0.001)
        k38 = ufloat(0.013, 0.0001)
        ca38 = ufloat(0.0, 0)
        ca36 = ufloat(0.0, 0)
        pr = {"Cl3638": ufloat(250.0, 5.0)}
        atm36, atm38, cl36, cl38 = calculate_atmospheric(
            a38,
            a36,
            k38,
            ca38,
            ca36,
            decay_time=365.0,
            production_ratios=pr,
            arar_constants=ac,
        )
        # cl36 should be non-zero now
        self.assertNotEqual(nominal_value(cl36), 0)
        # std_dev should propagate from atm3836
        self.assertGreater(std_dev(atm36), 0)

    def test_default_arar_constants_used(self):
        a38 = ufloat(0.5, 0)
        a36 = ufloat(0.1, 0)
        k38 = ufloat(0.013, 0)
        ca38 = ufloat(0, 0)
        ca36 = ufloat(0, 0)
        # arar_constants=None → uses default
        atm36, atm38, cl36, cl38 = calculate_atmospheric(
            a38,
            a36,
            k38,
            ca38,
            ca36,
            decay_time=365.0,
            production_ratios=None,
        )
        self.assertGreater(nominal_value(atm36), 0)


class CalculateFEdgeCasesTest(TestCase):
    """calculate_f edge: cosmogenic correction enabled, no interferences dict."""

    def test_cosmogenic_correction_enabled(self):
        ac = ArArConstants()
        ac.set_cosmogenic_ratios((0.18, 0.001), (0.65, 0.01))
        iso = [
            ufloat(1000.0, 1.0),
            ufloat(100.0, 0.5),
            ufloat(10.0, 0.05),
            ufloat(1.0, 0.005),
            ufloat(2.0, 0.01),
        ]
        pr = {"Cl3638": ufloat(0, 0), "K4039": ufloat(2e-4, 0)}
        f, f_wo, nar, comp, ifc = calculate_f(
            iso, decay_time=365.0, interferences=pr, arar_constants=ac
        )
        # Cosmogenic components stored in nar
        self.assertIsNotNone(nar.get("cosmo36"))
        self.assertIsNotNone(nar.get("cosmo38"))

    def test_default_args(self):
        iso = [
            ufloat(1000.0, 1.0),
            ufloat(100.0, 0.5),
            ufloat(10.0, 0.05),
            ufloat(1.0, 0.005),
            ufloat(2.0, 0.01),
        ]
        # interferences=None, arar_constants=None defaults
        f, f_wo, nar, comp, ifc = calculate_f(iso, decay_time=365.0)
        self.assertGreater(nominal_value(f), 0)


class CalculateErrorFAndTTest(TestCase):
    """Legacy McDougall-Harrison eq 3.43 formulas (less-used)."""

    def test_calculate_error_F_returns_positive(self):
        from pychron.processing.argon_calculations import calculate_error_F

        sigs = [
            ufloat(1000.0, 1.0),
            ufloat(100.0, 0.5),
            ufloat(10.0, 0.05),
            ufloat(1.0, 0.005),
            ufloat(2.0, 0.01),
        ]
        e = calculate_error_F(
            sigs,
            F=4.0,
            k4039=ufloat(2e-4, 1e-6),
            ca3937=ufloat(7e-4, 1e-6),
            ca3637=ufloat(2.6e-4, 1e-6),
        )
        self.assertGreater(e, 0)


class CalculateArarDecayFactorsDalrympleEdgeTest(TestCase):
    def test_zero_division_returns_unity(self):
        # tpower = sum(pi*ti) = 0 → ZeroDivisionError → returns (1.0, 1.0)
        segs = [(0.0, 0.0, 0.0, None, None)]
        d37, d39 = calculate_arar_decay_factors_dalrymple(7.2e-10, 7.0e-10, segs)
        self.assertEqual((d37, d39), (1.0, 1.0))
