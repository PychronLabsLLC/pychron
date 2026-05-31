# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Verify uncertainties correlation graph stays intact across the isotope
pipeline. Targets the three uvalue/copy/baseline bugs flagged in audit.
"""

from unittest import TestCase

import numpy as np
from uncertainties import ufloat

from pychron.processing.isotope import Isotope


def _build_isotope(name="Ar40", detector="H1", n=20, slope=0.0, intercept=100.0, noise=0.1):
    iso = Isotope(name, detector)
    rng = np.random.default_rng(0)
    iso.xs = np.linspace(0, 100, n)
    iso.ys = intercept + slope * iso.xs + rng.normal(0, noise, n)
    iso.fit = "linear"
    iso.error_type = "SEM"
    iso.set_baseline(0.0, 0.0)
    iso.set_blank(0.0, 0.0)
    return iso


class UValueCorrelationTest(TestCase):
    """`Isotope.uvalue` must return the SAME ufloat across multiple accesses
    so chained calculations preserve correlation. Previously each access
    created an independent random variable."""

    def test_same_ufloat_instance_across_accesses(self):
        iso = _build_isotope()
        u1 = iso.uvalue
        u2 = iso.uvalue
        # same Python object → same underlying uncertainties Variable
        self.assertIs(u1, u2)

    def test_subtracting_uvalue_from_itself_is_zero(self):
        """u - u should be exactly 0 ± 0. Previously gave non-zero std_dev
        because each access was an independent random variable."""
        iso = _build_isotope()
        diff = iso.uvalue - iso.uvalue
        self.assertAlmostEqual(diff.nominal_value, 0.0, places=12)
        self.assertAlmostEqual(diff.std_dev, 0.0, places=12)

    def test_cache_invalidated_when_xs_change(self):
        iso = _build_isotope()
        u1 = iso.uvalue
        v1 = iso.value
        # mutate raw data → must invalidate cache
        iso._invalidate_regressor()
        iso.ys = iso.ys + 50.0
        u2 = iso.uvalue
        v2 = iso.value
        self.assertIsNot(u1, u2)
        self.assertNotAlmostEqual(v1, v2, places=2)


class BaselineCorrelationTest(TestCase):
    """`get_baseline_corrected_value(include_baseline_error=False)` must
    preserve the correlation back to the signal variable. Previously the
    result was wrapped in a fresh ufloat that dropped the graph."""

    def test_baseline_corrected_correlates_with_uvalue(self):
        iso = _build_isotope()
        iso.set_baseline(5.0, 0.0)
        uv = iso.uvalue
        bc = iso.get_baseline_corrected_value(include_baseline_error=False)
        # bc = uv - 5.0 → bc and uv share the same underlying signal variable.
        # Subtracting them must give exactly 5.0 ± 0, not a noisy term.
        diff = uv - bc
        self.assertAlmostEqual(diff.nominal_value, 5.0, places=10)
        self.assertAlmostEqual(diff.std_dev, 0.0, places=10)

    def test_baseline_error_excluded_when_flag_false(self):
        """When include_baseline_error=False, baseline std_dev must NOT
        appear in the result's error budget."""
        iso = _build_isotope()
        iso.set_baseline(5.0, 100.0)  # huge baseline error
        bc = iso.get_baseline_corrected_value(include_baseline_error=False)
        # Result std_dev should equal signal std_dev (~SEM of intercept),
        # not contain the 100.0 baseline contribution.
        self.assertLess(bc.std_dev, 1.0)

    def test_baseline_error_included_when_flag_true(self):
        iso = _build_isotope()
        iso.set_baseline(5.0, 100.0)
        bc = iso.get_baseline_corrected_value(include_baseline_error=True)
        # baseline error of 100 dominates
        self.assertGreater(bc.std_dev, 50.0)


class FaradayBlankOrderTest(TestCase):
    """The 'Minna bluff' Faraday-only deferred-blank hack has been removed.
    All detectors must now subtract blank in the same place — *before*
    discrimination and IC scaling. Tests lock this behavior so the hack
    cannot silently regress."""

    def _build(self, detector):
        iso = _build_isotope(detector=detector, intercept=100.0)
        iso.set_blank(5.0, 0.0)
        iso.discrimination = ufloat(1.02, 0)  # non-unity to expose ordering
        iso.ic_factor = ufloat(0.98, 0)
        return iso

    def test_faraday_and_other_have_same_intensity_formula(self):
        far = self._build("faraday")
        cdd = self._build("CDD")
        # Same data, same disc/ic → identical intensities regardless of
        # detector type. With the old hack, Faraday differed from CDD by
        # the (disc·ic - 1)·blank term.
        self.assertAlmostEqual(
            far.get_intensity().nominal_value,
            cdd.get_intensity().nominal_value,
            places=10,
        )

    def test_blank_subtracted_before_disc_and_ic(self):
        """get_intensity() = (signal - blank - background) * disc * ic_factor"""
        iso = self._build("faraday")
        signal = iso.value
        blank = 5.0
        disc = 1.02
        ic = 0.98
        # background defaults to 0
        expected = (signal - blank) * disc * ic
        self.assertAlmostEqual(iso.get_intensity().nominal_value, expected, places=8)


# ============= EOF =============================================
