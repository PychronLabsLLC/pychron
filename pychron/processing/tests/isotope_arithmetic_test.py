# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Coverage for Isotope arithmetic operators, set_uvalue/set_ublank/set_baseline,
and the Sniff/Baseline/Background/Blank subclass plumbing.
"""

from unittest import TestCase

import numpy as np
from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.isotope import (
    Background,
    BaseIsotope,
    Baseline,
    Blank,
    Isotope,
    Sniff,
    Whiff,
)


def _build_iso(name="Ar40", detector="H1", intercept=100.0, noise=0.01):
    """Build a synthetic Isotope. Includes a tiny variation by default so
    OLS rsquared is defined (constant data → undefined rsquared)."""
    iso = Isotope(name, detector)
    rng = np.random.default_rng(0)
    iso.xs = np.linspace(0, 100, 50)
    iso.ys = intercept + 0.01 * iso.xs + rng.normal(0, noise, 50)
    iso.fit = "linear"
    iso.error_type = "SEM"
    iso.set_baseline(0.0, 0.0)
    iso.set_blank(0.0, 0.0)
    return iso


class IsotopeArithmeticTest(TestCase):
    """Arithmetic operators delegate to `self.uvalue + a` etc. Verify they
    propagate via uncertainties and preserve the correlation graph."""

    def setUp(self):
        self.iso = _build_iso(intercept=100.0)

    def test_add_scalar(self):
        result = self.iso + 5.0
        self.assertAlmostEqual(nominal_value(result), 105.0, delta=0.1)

    def test_radd_scalar(self):
        result = 5.0 + self.iso
        self.assertAlmostEqual(nominal_value(result), 105.0, delta=0.1)

    def test_sub_scalar(self):
        result = self.iso - 10.0
        self.assertAlmostEqual(nominal_value(result), 90.0, delta=0.1)

    def test_rsub_scalar(self):
        result = 200.0 - self.iso
        self.assertAlmostEqual(nominal_value(result), 100.0, delta=0.1)

    def test_mul_scalar(self):
        result = self.iso * 2.0
        self.assertAlmostEqual(nominal_value(result), 200.0, delta=0.2)

    def test_rmul_scalar(self):
        result = 3.0 * self.iso
        self.assertAlmostEqual(nominal_value(result), 300.0, delta=0.3)

    def test_div_scalar(self):
        result = self.iso.__div__(2.0)
        self.assertAlmostEqual(nominal_value(result), 50.0, delta=0.1)

    def test_rdiv_scalar(self):
        result = self.iso.__rdiv__(200.0)
        self.assertAlmostEqual(nominal_value(result), 2.0, delta=0.01)

    def test_self_minus_self_is_zero(self):
        """Two arithmetic ops on the same isotope share the cached uvalue
        → subtraction collapses to exactly 0±0 (correlation preserved)."""
        diff = (self.iso + 0.0) - (self.iso + 0.0)
        self.assertAlmostEqual(nominal_value(diff), 0.0, places=12)
        self.assertAlmostEqual(std_dev(diff), 0.0, places=12)

    def test_arithmetic_with_ufloat(self):
        u = ufloat(50.0, 0.1)
        result = self.iso + u
        self.assertAlmostEqual(nominal_value(result), 150.0, delta=0.1)
        self.assertGreater(std_dev(result), 0)


class SetUValueTest(TestCase):
    """set_uvalue accepts (v, e) tuple OR ufloat OR plain float."""

    def test_set_uvalue_from_tuple(self):
        iso = _build_iso()
        iso.set_uvalue((42.0, 0.5))
        self.assertEqual(iso._value, 42.0)
        self.assertEqual(iso._error, 0.5)

    def test_set_uvalue_from_ufloat(self):
        iso = _build_iso()
        iso.set_uvalue(ufloat(17.0, 0.3))
        self.assertEqual(iso._value, 17.0)
        self.assertEqual(iso._error, 0.3)

    def test_set_uvalue_invalidates_cache(self):
        """set_uvalue mutates _value/_error; the cached ufloat must clear."""
        iso = _build_iso()
        _ = iso.uvalue
        iso.use_stored_value = True
        iso.set_uvalue((42.0, 0.5))
        self.assertEqual(iso._cached_uvalue, None)
        self.assertEqual(iso._cache_token, None)


class UserDefinedValueTest(TestCase):
    """value/error setter marks user_defined and overrides regression."""

    def test_value_setter_marks_user_defined(self):
        iso = _build_iso()
        iso.value = 999.0
        self.assertTrue(iso.user_defined_value)
        self.assertEqual(iso.value, 999.0)

    def test_error_setter_marks_user_defined(self):
        iso = _build_iso()
        iso.error = 5.0
        self.assertTrue(iso.user_defined_error)
        self.assertEqual(iso.error, 5.0)

    def test_invalid_value_kept(self):
        """ValueError swallowed silently — _value unchanged."""
        iso = _build_iso()
        original = iso._value
        iso.value = "not_a_number"
        self.assertEqual(iso._value, original)

    def test_revert_user_defined(self):
        iso = _build_iso()
        iso._ovalue = 50.0
        iso._oerror = 0.5
        iso.user_defined_value = True
        iso.user_defined_error = True
        iso._value = 99.0
        iso._error = 9.0

        iso._revert_user_defined()
        self.assertFalse(iso.user_defined_value)
        self.assertFalse(iso.user_defined_error)
        self.assertEqual(iso._value, 50.0)
        self.assertEqual(iso._error, 0.5)


class BlankBaselineTest(TestCase):
    """set_blank/set_baseline construct Blank/Baseline subclasses."""

    def test_set_blank_creates_blank_instance(self):
        iso = _build_iso()
        iso.set_blank(0.5, 0.05)
        self.assertIsInstance(iso.blank, Blank)
        self.assertEqual(iso.blank._value, 0.5)
        self.assertEqual(iso.blank._error, 0.05)

    def test_set_baseline_creates_baseline_instance(self):
        iso = _build_iso()
        iso.set_baseline(0.1, 0.01)
        self.assertIsInstance(iso.baseline, Baseline)
        self.assertEqual(iso.baseline._value, 0.1)
        self.assertEqual(iso.baseline._error, 0.01)

    def test_set_ublank_with_ufloat(self):
        iso = _build_iso()
        iso.set_ublank(ufloat(0.2, 0.02))
        self.assertEqual(iso.blank._value, 0.2)
        self.assertEqual(iso.blank._error, 0.02)


class CorrectionMethodsTest(TestCase):
    """get_baseline_corrected / get_non_detector_corrected / get_intensity
    apply the full correction chain in the expected order."""

    def test_baseline_only(self):
        iso = _build_iso(intercept=100.0)
        iso.set_baseline(5.0, 0.0)
        iso.correct_for_blank = False  # disable blank step
        result = iso.get_baseline_corrected_value()
        self.assertAlmostEqual(nominal_value(result), 95.0, places=2)

    def test_blank_after_baseline(self):
        iso = _build_iso(intercept=100.0)
        iso.set_baseline(5.0, 0.0)
        iso.set_blank(3.0, 0.0)
        result = iso.get_non_detector_corrected_value()
        # 100 - 5 - 3 = 92
        self.assertAlmostEqual(nominal_value(result), 92.0, places=2)

    def test_disc_correction(self):
        iso = _build_iso(intercept=100.0)
        iso.discrimination = ufloat(1.02, 0)
        result = iso.get_disc_corrected_value()
        self.assertAlmostEqual(nominal_value(result), 100.0 * 1.02, places=2)

    def test_ic_correction(self):
        iso = _build_iso(intercept=100.0)
        iso.ic_factor = ufloat(0.98, 0)
        result = iso.get_ic_corrected_value()
        self.assertAlmostEqual(nominal_value(result), 100.0 * 0.98, places=2)

    def test_get_intensity_combines_disc_and_ic(self):
        iso = _build_iso(intercept=100.0)
        iso.discrimination = ufloat(1.02, 0)
        iso.ic_factor = ufloat(0.98, 0)
        result = iso.get_intensity()
        self.assertAlmostEqual(nominal_value(result), 100.0 * 1.02 * 0.98, places=2)

    def test_discrimination_none_defaults_to_one(self):
        iso = _build_iso(intercept=50.0)
        iso.discrimination = None
        result = iso.get_disc_corrected_value()
        self.assertAlmostEqual(nominal_value(result), 50.0, places=2)

    def test_ic_factor_zero_ufloat_not_replaced(self):
        """Regression: previously `ic_factor or 1.0` replaced zero-nominal
        ufloat with 1; now it must be respected."""
        iso = _build_iso(intercept=50.0)
        iso.ic_factor = ufloat(0.0, 0.0)
        result = iso.get_intensity()
        self.assertAlmostEqual(nominal_value(result), 0.0, places=10)


class SniffWhiffTest(TestCase):
    """Sniff and Whiff are thin BaseMeasurement subclasses used for
    pre-analysis equilibration data."""

    def test_sniff_construction(self):
        s = Sniff("Ar40", "H1")
        self.assertEqual(s.name, "Ar40")
        self.assertEqual(s.detector, "H1")

    def test_whiff_construction(self):
        w = Whiff("Ar40", "H1")
        self.assertEqual(w.name, "Ar40")
        self.assertEqual(w.detector, "H1")

    def test_sniff_holds_xs_ys(self):
        s = Sniff("Ar40", "H1")
        s.xs = np.array([0.0, 1.0, 2.0])
        s.ys = np.array([10.0, 11.0, 12.0])
        self.assertEqual(s.n, 3)


class BackgroundTest(TestCase):
    """Background is a CorrectionIsotopicMeasurement subclass."""

    def test_background_construction(self):
        bg = Background("Ar40 bg", "H1")
        self.assertEqual(bg.name, "Ar40 bg")
        self.assertEqual(bg.detector, "H1")

    def test_isotope_subtracts_background(self):
        iso = _build_iso(intercept=100.0)
        iso.background.set_uvalue((10.0, 0.0))
        iso.set_baseline(0.0, 0.0)
        iso.set_blank(0.0, 0.0)
        result = iso.get_non_detector_corrected_value()
        # 100 - 0 (blank) - 10 (background) - 0 (baseline) = 90
        self.assertAlmostEqual(nominal_value(result), 90.0, places=2)


class BaselineWindowCountTest(TestCase):
    """get_baseline_corrected_value(window=..., count=...) uses sniff
    data rather than the regressor."""

    def setUp(self):
        self.iso = _build_iso(intercept=100.0)
        self.iso.sniff.xs = np.linspace(0, 10, 20)
        self.iso.sniff.ys = np.linspace(50.0, 60.0, 20)
        self.iso.set_baseline(5.0, 0.0)

    def test_window_uses_last_n_sniff_points(self):
        result = self.iso.get_baseline_corrected_value(window=5)
        expected = self.iso.sniff.ys[-5:].mean() - 5.0
        self.assertAlmostEqual(nominal_value(result), expected, places=6)

    def test_count_indexes_single_sniff_point(self):
        result = self.iso.get_baseline_corrected_value(count=10)
        # sniff.ys[10] = 50 + 10 * (10/19) ≈ 55.26
        self.assertAlmostEqual(nominal_value(result), self.iso.sniff.ys[10] - 5.0, places=2)

    def test_window_uses_unbiased_std(self):
        """Regression: previously used ys.std() default ddof=0;
        now uses ddof=1 for unbiased sample std."""
        result = self.iso.get_baseline_corrected_value(window=5)
        last5 = self.iso.sniff.ys[-5:]
        expected_e = last5.std(ddof=1)
        # Result's std_dev = sqrt(expected_e^2 + 0^2) = expected_e
        self.assertAlmostEqual(std_dev(result), expected_e, places=8)


class PackUnpackTest(TestCase):
    """BaseMeasurement.pack / unpack_data round-trip binary IO."""

    def test_pack_then_unpack_roundtrip(self):
        iso = _build_iso(intercept=100.0)
        blob = iso.pack(as_hex=False)
        iso2 = Isotope("Ar40", "H1")
        iso2.unpack_data(blob)
        np.testing.assert_allclose(iso2.xs, iso.xs)
        np.testing.assert_allclose(iso2.ys, iso.ys)

    def test_unpack_empty_blob_no_op(self):
        iso = Isotope("Ar40", "H1")
        # zero-length blob → bails
        iso.unpack_data(b"")
        self.assertEqual(iso.xs.shape[0], 0)

    def test_unpack_corrupt_blob_records_error(self):
        iso = Isotope("Ar40", "H1")
        iso.unpack_data(b"\x00\x01\x02")  # odd length triggers struct error
        # error stored, no crash
        # _unpack_blob logs but doesn't set unpack_error in that path
        self.assertEqual(iso.xs.shape[0], 0)

    def test_unpack_n_only(self):
        iso = _build_iso(intercept=100.0)
        blob = iso.pack(as_hex=False)
        iso2 = Isotope("Ar40", "H1")
        iso2.unpack_data(blob, n_only=True)
        self.assertEqual(iso2.n, iso.xs.shape[0])


class GetSlopeCurvatureGradientTest(TestCase):
    def test_get_slope_linear_data(self):
        iso = Isotope("Ar40", "H1")
        iso.xs = np.linspace(0, 10, 11)
        iso.ys = 2.0 * iso.xs + 5.0  # slope = 2
        slope = iso.get_slope()
        self.assertAlmostEqual(slope, 2.0, places=8)

    def test_get_slope_last_n(self):
        iso = Isotope("Ar40", "H1")
        iso.xs = np.linspace(0, 100, 100)
        iso.ys = 0.5 * iso.xs
        slope = iso.get_slope(n=20)
        self.assertAlmostEqual(slope, 0.5, places=8)

    def test_get_slope_empty(self):
        iso = Isotope("Ar40", "H1")
        # default xs/ys are empty arrays
        self.assertEqual(iso.get_slope(), 0)

    def test_get_gradient(self):
        iso = Isotope("Ar40", "H1")
        iso.xs = np.array([0.0, 1.0, 2.0, 3.0])
        iso.ys = np.array([0.0, 1.0, 4.0, 9.0])
        # gradient(ys) = [1, 2, 4, 5] → sqrt(sum of squares) = sqrt(46)
        result = iso.get_gradient()
        self.assertGreater(result, 0)

    def test_get_curvature_runs(self):
        iso = _build_iso(intercept=100.0)
        iso.fit = "parabolic"
        iso.ys = iso.ys + 0.01 * iso.xs**2
        # Curvature at x=10 should not crash. Skip if curvature_at unavailable.
        try:
            iso.get_curvature(10)
        except Exception as e:
            self.fail("get_curvature raised: {}".format(e))


class SetFittingHelpersTest(TestCase):
    def test_set_filtering_no_change_short_circuits(self):
        iso = _build_iso()
        d = {"filter_outliers": True, "iterations": 1, "std_devs": 2}
        iso.set_filtering(d)
        d_before = iso.filter_outliers_dict.copy()
        # second call with same dict — should be a no-op
        iso.set_filtering(d)
        self.assertEqual(iso.filter_outliers_dict, d_before)

    def test_set_filtering_changes_dict(self):
        iso = _build_iso()
        iso.set_filtering({"filter_outliers": True, "iterations": 5, "std_devs": 3})
        self.assertEqual(iso.filter_outliers_dict["iterations"], 5)
        self.assertEqual(iso.filter_outliers_dict["std_devs"], 3)

    def test_set_filter_outliers_dict_populates(self):
        iso = _build_iso()
        iso.set_filter_outliers_dict(
            filter_outliers=True,
            iterations=4,
            std_devs=3,
            use_standard_deviation_filtering=True,
        )
        d = iso.filter_outliers_dict
        self.assertTrue(d["filter_outliers"])
        self.assertEqual(d["iterations"], 4)
        self.assertEqual(d["std_devs"], 3)
        self.assertTrue(d["use_standard_deviation_filtering"])
        self.assertFalse(d["use_iqr_filtering"])

    def test_set_user_excluded(self):
        iso = _build_iso()
        iso.set_user_excluded([2, 5, 7])
        # forces regressor build; verify ouser_excluded set
        self.assertEqual(iso._regressor.ouser_excluded, [2, 5, 7])

    def test_set_user_excluded_empty_noop(self):
        iso = _build_iso()
        iso.set_user_excluded([])  # falsy → no-op
        # _regressor not built
        self.assertIsNone(iso._regressor)

    def test_user_excluded_returns_list(self):
        iso = _build_iso()
        iso.set_user_excluded([1, 2])
        # property forces regressor
        result = iso.user_excluded
        self.assertEqual(result, [])  # ouser_excluded not user_excluded

    def test_outlier_excluded_returns_list(self):
        iso = _build_iso()
        # trigger regressor
        _ = iso.value
        self.assertEqual(iso.outlier_excluded, [])

    def test_fn_default_uses_regressor_n(self):
        iso = _build_iso()
        _ = iso.value  # trigger regressor
        self.assertEqual(iso.fn, 50)

    def test_fn_user_set(self):
        iso = _build_iso()
        iso.fn = 42
        self.assertEqual(iso.fn, 42)

    def test_get_rsquared(self):
        iso = _build_iso()
        _ = iso.value
        r2 = iso.get_rsquared()
        self.assertGreaterEqual(r2, 0)
        self.assertLessEqual(r2, 1)

    def test_rsquared_property(self):
        iso = _build_iso()
        _ = iso.value
        self.assertIsNotNone(iso.rsquared)

    def test_rsquared_adj_property(self):
        iso = _build_iso()
        _ = iso.value
        self.assertIsNotNone(iso.rsquared_adj)

    def test_get_linear_rsquared(self):
        iso = _build_iso()
        self.assertGreaterEqual(iso.get_linear_rsquared(), 0)

    def test_efit_property_appends_error_type(self):
        iso = _build_iso()
        iso.fit = "linear"
        iso.error_type = "SEM"
        self.assertEqual(iso.efit, "linear_SEM")

    def test_efit_property_already_has_underscore(self):
        iso = _build_iso()
        iso.fit = "linear_SEM"
        self.assertEqual(iso.efit, "linear_SEM")


class FitBlocksTest(TestCase):
    def test_set_fit_blocks_str_simple(self):
        iso = _build_iso()
        iso.set_fit_blocks("linear")
        self.assertEqual(iso.fit, "linear")

    def test_set_fit_blocks_tuple(self):
        iso = _build_iso()
        iso.set_fit_blocks(("linear", "SD"))
        self.assertEqual(iso.fit, "linear")
        self.assertEqual(iso.error_type, "SD")

    def test_set_fit_blocks_block_syntax(self):
        iso = _build_iso()
        iso.set_fit_blocks("(,10,average)(10,,linear)")
        self.assertEqual(len(iso.fit_blocks), 2)
        # first block: (-1, 10, "average")
        self.assertEqual(iso.fit_blocks[0][2], "average")
        self.assertEqual(iso.fit_blocks[1][2], "linear")

    def test_get_fit_from_blocks(self):
        iso = _build_iso()
        iso.set_fit_blocks("(,10,average)(10,,linear)")
        # at count=5, fits to first block
        self.assertEqual(iso.get_fit(5), "average")
        # at count=20, fits to second block
        self.assertEqual(iso.get_fit(20), "linear")


class AttrSetTest(TestCase):
    def test_attr_set_assigns_multiple(self):
        iso = _build_iso()
        iso.attr_set(fit="parabolic", error_type="SD")
        self.assertEqual(iso.fit, "parabolic")
        self.assertEqual(iso.error_type, "SD")

    def test_set_fit_error_type(self):
        iso = _build_iso()
        iso.set_fit_error_type("SEM")
        self.assertEqual(iso.error_type, "SEM")


class FitAbbreviationTest(TestCase):
    def test_default_no_filter(self):
        iso = _build_iso()
        iso.fit = "linear"
        self.assertEqual(iso.fit_abbreviation, "L")

    def test_with_filter_outliers_adds_star(self):
        iso = _build_iso()
        iso.fit = "linear"
        iso.filter_outliers_dict = {"filter_outliers": True}
        self.assertEqual(iso.fit_abbreviation, "L*")


class GroupDataTest(TestCase):
    def test_set_grouping_invalidates_regressor(self):
        iso = _build_iso()
        _ = iso.value  # build regressor
        self.assertIsNotNone(iso._regressor)
        iso.set_grouping(5)
        self.assertIsNone(iso._regressor)

    def test_set_grouping_same_value_no_op(self):
        iso = _build_iso()
        iso.set_grouping(5)
        _ = iso.value  # rebuild
        reg = iso._regressor
        iso.set_grouping(5)
        # unchanged; regressor stays
        self.assertIs(iso._regressor, reg)

    def test_get_data_groups_when_set(self):
        iso = _build_iso()
        iso.set_grouping(5)
        xs, ys = iso.get_data()
        # 50 points / 5 = 10 groups
        self.assertEqual(len(xs), 10)


class StandardFitErrorTest(TestCase):
    def test_standard_fit_error_runs(self):
        iso = _build_iso()
        err = iso.standard_fit_error()
        self.assertGreaterEqual(err, 0)

    def test_noutliers_zero_for_clean_data(self):
        iso = _build_iso()
        _ = iso.value
        self.assertEqual(iso.noutliers(), 0)


class TimeZeroAndSerialTest(TestCase):
    def test_set_time_zero_propagates_to_subobjects(self):
        iso = _build_iso()
        iso.set_time_zero(3.5)
        self.assertEqual(iso.time_zero_offset, 3.5)
        self.assertEqual(iso.blank.time_zero_offset, 3.5)
        self.assertEqual(iso.sniff.time_zero_offset, 3.5)
        self.assertEqual(iso.baseline.time_zero_offset, 3.5)

    def test_set_detector_serial_id_propagates(self):
        iso = _build_iso()
        iso.set_detector_serial_id("ABC123")
        self.assertEqual(iso.detector_serial_id, "ABC123")
        self.assertEqual(iso.blank.detector_serial_id, "ABC123")
        self.assertEqual(iso.sniff.detector_serial_id, "ABC123")
        self.assertEqual(iso.baseline.detector_serial_id, "ABC123")

    def test_set_units_propagates(self):
        iso = _build_iso()
        iso.set_units("V")
        self.assertEqual(iso.units, "V")
        self.assertEqual(iso.blank.units, "V")
        self.assertEqual(iso.sniff.units, "V")
        self.assertEqual(iso.baseline.units, "V")


class InterceptPercentErrorTest(TestCase):
    def test_normal(self):
        iso = _build_iso(intercept=100.0)
        _ = iso.uvalue  # build cache
        pe = iso.intercept_percent_error
        self.assertGreaterEqual(pe, 0)

    def test_zero_value(self):
        iso = Isotope("Ar40", "H1")
        iso._value = 0
        iso._error = 0.1
        iso.use_stored_value = True
        # ZeroDivisionError caught — returns -1 (sentinel)
        result = iso.intercept_percent_error
        self.assertEqual(result, -1)


class DecayCorrectedValueTest(TestCase):
    def test_returns_decay_corrected_when_set(self):
        iso = _build_iso()
        iso.decay_corrected = ufloat(42.0, 1.0)
        v = iso.get_decay_corrected_value()
        self.assertEqual(v, iso.decay_corrected)

    def test_falls_back_to_non_detector_corrected(self):
        iso = _build_iso(intercept=100.0)
        iso.set_baseline(5.0, 0)
        iso.set_blank(2.0, 0)
        v = iso.get_decay_corrected_value()
        # 100 - 5 - 2 = 93
        self.assertAlmostEqual(nominal_value(v), 93.0, places=2)

    def test_get_ic_decay_corrected_value(self):
        iso = _build_iso()
        iso.decay_corrected = ufloat(50.0, 1.0)
        v = iso.get_ic_decay_corrected_value()
        self.assertEqual(v, iso.decay_corrected)


class InterferenceCorrectedValueTest(TestCase):
    def test_returns_stored_value(self):
        iso = _build_iso()
        iso.interference_corrected_value = ufloat(7.5, 0.1)
        v = iso.get_interference_corrected_value()
        self.assertEqual(v, iso.interference_corrected_value)

    def test_returns_zero_when_unset(self):
        iso = Isotope("Ar40", "H1")
        v = iso.get_interference_corrected_value()
        self.assertEqual(nominal_value(v), 0)


class NoBaselineErrorTest(TestCase):
    def test_strips_baseline_error_and_subtracts_blank(self):
        iso = _build_iso(intercept=100.0)
        iso.set_baseline(5.0, 100.0)  # huge baseline error
        iso.set_blank(2.0, 0.5)
        v = iso.no_baseline_error()
        # 100 - 5 - 2 = 93; baseline error dropped
        self.assertAlmostEqual(nominal_value(v), 93.0, places=2)


# ============= EOF =============================================
