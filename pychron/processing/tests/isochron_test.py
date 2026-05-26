# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Tests for the Ar/Ar isochron path:
  extract_isochron_xy → isochron_regressor → calculate_isochron.

Synthesizes step data with a known mixing line between atmospheric and
radiogenic 40Ar/39Ar/36Ar so the inverse isochron should land on
   y-intercept = 1/atm4036
   x-intercept = 1/F   (F = rad40/39ArK at the known age)
and the recovered age must match the input age.
"""

import math
from unittest import TestCase

import numpy as np
from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.arar_constants import ArArConstants
from pychron.processing.argon_calculations import (
    age_equation,
    calculate_isochron,
    extract_isochron_xy,
    get_isochron_regressors,
    isochron_regressor,
    unpack_value_error,
)


class _Analysis:
    """Minimal analysis stub for the isochron functions."""

    def __init__(self, ar39, ar36, ar40, j=None, arar_constants=None):
        self._vals = {"Ar39": ar39, "Ar36": ar36, "Ar40": ar40}
        self.j = j
        self.arar_constants = arar_constants

    def get_interference_corrected_value(self, name):
        return self._vals[name]


def _build_steps(age_ma=10.0, j=1e-3, n=5, atm_fractions=None):
    """Generate n analyses on a known isochron mixing line."""
    ac = ArArConstants()
    lk = nominal_value(ac.lambda_k)
    age_yr = age_ma * 1e6
    # F = (exp(λ·t) - 1) / J
    F = (math.exp(lk * age_yr) - 1) / j
    atm = nominal_value(ac.atm4036)

    if atm_fractions is None:
        atm_fractions = np.linspace(0.1, 0.5, n)

    total40 = 1000.0
    analyses = []
    for i, f_atm in enumerate(atm_fractions):
        atm40 = f_atm * total40
        rad40 = (1 - f_atm) * total40
        a40 = ufloat(total40, total40 * 0.001, tag="Ar40_{}".format(i))
        a36 = ufloat(atm40 / atm, atm40 / atm * 0.005, tag="Ar36_{}".format(i))
        a39 = ufloat(rad40 / F, rad40 / F * 0.002, tag="Ar39_{}".format(i))
        analyses.append(_Analysis(a39, a36, a40, j=ufloat(j, j * 0.001), arar_constants=ac))

    return analyses, F, atm, age_yr


class ExtractIsochronXYTest(TestCase):
    """`extract_isochron_xy(analyses)` returns (xx=39/40, yy=36/40, a39, a36, a40)."""

    def test_returns_five_arrays(self):
        analyses, _, _, _ = _build_steps()
        result = extract_isochron_xy(analyses)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 5)
        xx, yy, a39, a36, a40 = result
        self.assertEqual(len(xx), len(analyses))

    def test_xx_equals_a39_over_a40(self):
        analyses, _, _, _ = _build_steps()
        xx, yy, a39, a36, a40 = extract_isochron_xy(analyses)
        for x, n, d in zip(xx, a39, a40):
            self.assertAlmostEqual(nominal_value(x), nominal_value(n) / nominal_value(d), places=10)

    def test_yy_equals_a36_over_a40(self):
        analyses, _, _, _ = _build_steps()
        xx, yy, a39, a36, a40 = extract_isochron_xy(analyses)
        for y, n, d in zip(yy, a36, a40):
            self.assertAlmostEqual(nominal_value(y), nominal_value(n) / nominal_value(d), places=10)


class UnpackValueErrorTest(TestCase):
    def test_returns_two_lists(self):
        xs = [ufloat(1.0, 0.1), ufloat(2.0, 0.2), ufloat(3.0, 0.3)]
        ns, es = unpack_value_error(xs)
        self.assertEqual(ns, [1.0, 2.0, 3.0])
        self.assertEqual(es, [0.1, 0.2, 0.3])

    def test_empty_input(self):
        ns, es = unpack_value_error([])
        self.assertEqual(ns, [])
        self.assertEqual(es, [])


class IsochronRegressorFactoryTest(TestCase):
    """`isochron_regressor` factory dispatches on kind string."""

    def setUp(self):
        self.kw = dict(
            xs=[1.0, 2.0, 3.0, 4.0, 5.0],
            xes=[0.01, 0.01, 0.01, 0.01, 0.01],
            ys=[1.0, 2.1, 3.0, 4.1, 5.0],
            yes=[0.01, 0.01, 0.01, 0.01, 0.01],
            xds=[10.0] * 5,
            xdes=[0.01] * 5,
            xns=[1.0] * 5,
            xnes=[0.01] * 5,
            yns=[1.0] * 5,
            ynes=[0.01] * 5,
        )

    def test_newyork(self):
        from pychron.core.regression.new_york_regressor import NewYorkRegressor

        r = isochron_regressor(reg="NewYork", **self.kw)
        self.assertIsInstance(r, NewYorkRegressor)

    def test_york(self):
        from pychron.core.regression.new_york_regressor import YorkRegressor

        r = isochron_regressor(reg="york", **self.kw)
        self.assertIsInstance(r, YorkRegressor)

    def test_reed_default_fallback(self):
        """Unknown kind falls through to ReedYorkRegressor."""
        from pychron.core.regression.new_york_regressor import ReedYorkRegressor

        r = isochron_regressor(reg="reed", **self.kw)
        self.assertIsInstance(r, ReedYorkRegressor)


class GetIsochronRegressorsTest(TestCase):
    """`get_isochron_regressors(a40, a39, a36)` returns (reg, regx)."""

    def test_returns_both_regressors(self):
        analyses, _, _, _ = _build_steps()
        _, _, a39, a36, a40 = extract_isochron_xy(analyses)
        reg, regx = get_isochron_regressors(a40, a39, a36)
        self.assertIsNotNone(reg)
        self.assertIsNotNone(regx)

    def test_reg_x_y_swapped_from_regx(self):
        analyses, _, _, _ = _build_steps()
        _, _, a39, a36, a40 = extract_isochron_xy(analyses)
        reg, regx = get_isochron_regressors(a40, a39, a36)
        # reg fits y(=36/40) vs x(=39/40); regx fits the inverse.
        # Both intercepts should be positive for a normal isochron.
        self.assertGreater(reg.get_intercept(), 0)
        self.assertGreater(regx.get_intercept(), 0)


class CalculateIsochronAgeRecoveryTest(TestCase):
    """Full pipeline: synthesize steps on a mixing line at known age,
    invert via `calculate_isochron`, recover the age."""

    def test_recovers_known_age(self):
        true_age_ma = 10.0
        analyses, F_true, atm_true, age_yr = _build_steps(age_ma=true_age_ma)
        result = calculate_isochron(analyses, error_calc_kind="SE")
        self.assertIsNotNone(result)
        age, yint, reg = result
        # Recovered age should be very close to truth (within ~0.1 Ma)
        self.assertAlmostEqual(nominal_value(age) / 1e6, true_age_ma, delta=0.1)

    def test_recovers_atmospheric_intercept(self):
        """y-intercept of normal isochron (36/40 vs 39/40 at x=0) is the
        atmospheric 36/40 ratio = 1/atm4036."""
        analyses, _, atm, _ = _build_steps()
        result = calculate_isochron(analyses, error_calc_kind="SE")
        age, yint, reg = result
        expected_yint = 1.0 / atm
        self.assertAlmostEqual(nominal_value(yint), expected_yint, places=4)

    def test_returns_none_on_empty(self):
        """analyses empty → extract returns None → calculate returns None."""
        # Mock a single analysis with a40=0 to force ZeroDivisionError
        ac = ArArConstants()
        bad = [
            _Analysis(
                ufloat(0, 0),
                ufloat(0, 0),
                ufloat(0, 0),
                j=ufloat(1e-3, 1e-6),
                arar_constants=ac,
            )
        ]
        # divide-by-zero in extract → returns None → calculate returns None
        result = calculate_isochron(bad, error_calc_kind="SE")
        self.assertIsNone(result)

    def test_include_j_err_toggles_error_propagation(self):
        analyses, _, _, _ = _build_steps()
        age_with, _, _ = calculate_isochron(analyses, error_calc_kind="SE", include_j_err=True)
        age_without, _, _ = calculate_isochron(analyses, error_calc_kind="SE", include_j_err=False)
        # Both should give the same nominal age
        self.assertAlmostEqual(nominal_value(age_with), nominal_value(age_without), places=2)
        # But include_j_err=True should have >= error
        self.assertGreaterEqual(std_dev(age_with), std_dev(age_without))

    def test_exclude_argument_drops_points(self):
        analyses, _, _, _ = _build_steps(n=7)
        # exclude the first 2 steps
        result = calculate_isochron(analyses, error_calc_kind="SE", exclude=[0, 1])
        self.assertIsNotNone(result)
        _, _, reg = result
        self.assertEqual(reg.user_excluded, [0, 1])


# ============= EOF =============================================
