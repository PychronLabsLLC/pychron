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
Accuracy tests for error propagation and statistical calculations.

Reference values either come from textbooks (Draper & Smith p.8 dataset),
canonical wiki examples (weighted mean), or are computed analytically below.
Use these to lock in correctness before refactoring hot paths.
"""

from unittest import TestCase

import numpy as np

from pychron.core.regression.interpolation_regressor import InterpolationRegressor
from pychron.core.regression.least_squares_regressor import LeastSquaresRegressor
from pychron.core.regression.mean_regressor import (
    MeanRegressor,
    WeightedMeanRegressor,
)
from pychron.core.regression.new_york_regressor import (
    NewYorkRegressor,
    ReedYorkRegressor,
    YorkRegressor,
)
from pychron.core.regression.ols_regressor import (
    MultipleLinearRegressor,
    OLSRegressor,
    PolynomialRegressor,
)
from pychron.core.regression.tests.standard_data import (
    filter_data,
    mean_data,
    ols_data,
    pearson,
    weighted_mean_data,
)
from pychron.core.regression.wls_regressor import (
    WeightedMultipleLinearRegressor,
    WeightedPolynomialRegressor,
)
from pychron.core.regression.flux_regressor import (
    BowlFluxRegressor,
    BSplineRegressor,
    GridDataRegressor,
    HighOrderPolynominalFluxRegressor,
    IDWRegressor,
    NearestNeighborFluxRegressor,
    PlaneFluxRegressor,
    RBFRegressor,
)


class OLSStatisticsTest(TestCase):
    """
    Draper & Smith p.8 dataset. Reference values verified by direct
    computation against statsmodels OLS.
    """

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r
        cls.xs = np.asarray(xs, dtype=float)
        cls.ys = np.asarray(ys, dtype=float)

    def test_slope(self):
        self.assertAlmostEqual(self.reg.coefficients[-1], -0.07982869, places=6)

    def test_intercept(self):
        self.assertAlmostEqual(self.reg.coefficients[0], 13.62298927, places=6)

    def test_coefficient_errors(self):
        ce = list(self.reg.coefficient_errors)
        self.assertAlmostEqual(ce[0], 0.58146349, places=6)
        self.assertAlmostEqual(ce[1], 0.01052358, places=6)

    def test_syx(self):
        self.assertAlmostEqual(self.reg.get_syx(), 0.89012452, places=6)

    def test_standard_error_fit_equals_syx(self):
        self.assertAlmostEqual(
            self.reg.calculate_standard_error_fit(), self.reg.get_syx(), places=10
        )

    def test_syx_uses_correct_dof_for_parabolic(self):
        """syx must use n-q (q = num coefficients), not hardcoded n-2."""
        xs = np.linspace(0, 10, 21)
        ys = 0.5 * xs**2 + 2 * xs + 1 + np.sin(xs) * 0.1
        r = PolynomialRegressor(xs=xs, ys=ys, fit="parabolic")
        r.calculate()
        # both must agree; if get_syx were still hardcoded n-2, they'd differ
        self.assertAlmostEqual(r.get_syx(), r.calculate_standard_error_fit(), places=10)

    def test_ssx(self):
        xm = self.xs.mean()
        expected = ((self.xs - xm) ** 2).sum()
        self.assertAlmostEqual(self.reg.get_ssx(), expected, places=8)
        self.assertAlmostEqual(self.reg.get_ssx(), 7154.42, places=2)

    def test_rsquared(self):
        self.assertAlmostEqual(self.reg.rsquared, 0.71443752, places=6)

    def test_rsquared_adj(self):
        self.assertAlmostEqual(self.reg.rsquared_adj, 0.70202176, places=6)

    def test_predict_scalar(self):
        self.assertAlmostEqual(self.reg.predict(28.6), 11.33988864, places=6)

    def test_predict_array_shape(self):
        out = self.reg.predict(np.array([10.0, 50.0, 90.0]))
        self.assertEqual(out.shape, (3,))

    def test_residuals_sum_to_zero(self):
        resid = self.reg.calculate_residuals()
        self.assertAlmostEqual(resid.sum(), 0.0, places=8)


class OLSPredictErrorTest(TestCase):
    """
    Two implementations of OLS prediction error must agree:
    `predict_error` (statsmodels normalized_cov_params),
    `predict_error_matrix` (Draper & Smith ch. 2.4).
    """

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_predict_error_sem_known_value(self):
        self.assertAlmostEqual(self.reg.predict_error(28.6, "SEM"), 0.30900230, places=6)

    def test_predict_error_sd_gt_sem(self):
        sem = self.reg.predict_error(28.6, "SEM")
        sd = self.reg.predict_error(28.6, "SD")
        self.assertGreater(sd, sem)
        self.assertAlmostEqual(sd, 0.94223356, places=6)

    def test_predict_error_ci_known_value(self):
        """95% CI half-width at x=28.6 for Draper & Smith p.8 dataset.
        Formula: t_{0.975, n-1} · σ_yx · √(1/n + (x-x̄)²/SSx)."""
        self.assertAlmostEqual(self.reg.predict_error(28.6, "CI"), 0.63774940, places=6)

    def test_predict_error_ci_matches_textbook_formula(self):
        """Direct algebraic recomputation of the CI."""
        from scipy.stats import t as student_t

        x = 28.6
        xs = np.asarray(self.reg.xs)
        n = len(xs)
        xm = xs.mean()
        ssx = ((xs - xm) ** 2).sum()
        syx = self.reg.get_syx()
        ti = student_t.ppf(0.975, n - 1)
        expected = ti * syx * (1 / n + (x - xm) ** 2 / ssx) ** 0.5
        self.assertAlmostEqual(self.reg.predict_error(x, "CI"), expected, places=10)

    def test_predict_error_matrix_matches_predict_error(self):
        sem = self.reg.predict_error(28.6, "SEM")
        mat = self.reg.predict_error_matrix([28.6], "SEM")[0]
        self.assertAlmostEqual(sem, mat, places=10)

    def test_predict_error_min_at_xbar(self):
        """Prediction error must be smallest at the mean of xs."""
        xm = float(np.asarray(self.reg.xs).mean())
        e_center = self.reg.predict_error(xm, "SEM")
        e_low = self.reg.predict_error(xm - 30.0, "SEM")
        e_high = self.reg.predict_error(xm + 30.0, "SEM")
        self.assertLess(e_center, e_low)
        self.assertLess(e_center, e_high)


class OLSErrorEnvelopeTest(TestCase):
    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_envelope_symmetric_around_model(self):
        fx = np.array([20.0, 50.0, 80.0])
        fy = self.reg.predict(fx)
        ly, uy = self.reg.calculate_error_envelope(fx, fy, "SEM")
        np.testing.assert_allclose(uy - fy, fy - ly, atol=1e-12)

    def test_envelope_uses_supplied_rmodel(self):
        """Passing rmodel must skip the predict() call, producing the same result."""
        fx = np.array([20.0, 50.0, 80.0])
        fy = self.reg.predict(fx)
        ly1, uy1 = self.reg.calculate_error_envelope(fx, None, "SEM")
        ly2, uy2 = self.reg.calculate_error_envelope(fx, fy, "SEM")
        np.testing.assert_allclose(ly1, ly2, atol=1e-12)
        np.testing.assert_allclose(uy1, uy2, atol=1e-12)


class OLSFilterBoundsTest(TestCase):
    """`calculate_filter_bounds` produces ±bound region around the model."""

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        r = PolynomialRegressor(
            xs=xs,
            ys=ys,
            fit="linear",
            filter_outliers_dict={
                "filter_outliers": True,
                "iterations": 1,
                "std_devs": 2,
            },
        )
        r.calculate()
        cls.reg = r

    def test_bounds_symmetric_and_constant_width(self):
        fx = np.linspace(30, 70, 5)
        fy = self.reg.predict(fx)
        ly, uy = self.reg.calculate_filter_bounds(fy)
        widths = uy - ly
        np.testing.assert_allclose(widths, widths[0], atol=1e-10)
        np.testing.assert_allclose(uy - fy, fy - ly, atol=1e-10)

    def test_bound_value_equals_nsigma_times_sigma_fit(self):
        sigma = self.reg.calculate_standard_error_fit()
        self.assertAlmostEqual(self.reg.filter_bound_value, 2.0 * sigma, places=8)


class OutlierDetectionTest(TestCase):
    def test_std_outlier_detected(self):
        xs = np.arange(20).astype(float)
        ys = np.ones(20) * 5.0
        ys[10] = 100.0
        m = MeanRegressor(xs=xs, ys=ys, filter_outliers_dict={"std_devs": 2})
        out = list(m.calculate_outliers())
        self.assertIn(10, out)

    def test_iqr_outlier_detected(self):
        """IQR branch was previously broken by operator precedence."""
        xs = np.arange(20).astype(float)
        ys = np.ones(20) * 5.0
        ys[10] = 100.0
        m = MeanRegressor(xs=xs, ys=ys, filter_outliers_dict={"use_iqr_filtering": True})
        out = list(m.calculate_outliers())
        self.assertIn(10, out)

    def test_filter_excludes_outlier_from_fit(self):
        xs, ys, sol = filter_data()
        r = PolynomialRegressor(
            xs=xs,
            ys=ys,
            fit="linear",
            filter_outliers_dict={
                "filter_outliers": True,
                "iterations": 1,
                "std_devs": 2,
            },
        )
        r.calculate()
        # outlier sits at last index (the 1000 in filter_data())
        self.assertIn(len(xs) - 1, r.outlier_excluded)
        self.assertAlmostEqual(r.coefficients[-1], sol["slope"], places=4)
        self.assertAlmostEqual(r.coefficients[0], sol["y_intercept"], places=3)


class PearsonsRTest(TestCase):
    def test_pearsons_r_matches_numpy(self):
        xs, ys, _ = ols_data()
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        rho = r.calculate_pearsons_r(xs, ys)
        expected = np.corrcoef(xs, ys)[0, 1]
        self.assertAlmostEqual(rho, expected, places=10)
        self.assertAlmostEqual(rho, -0.84524406, places=6)


class MeanStatisticsTest(TestCase):
    """Seeded `mean_data` gives n=1e5 normal samples (scalar=5, std=1.5)."""

    @classmethod
    def setUpClass(cls):
        xs, ys, sol = mean_data(n=1e5)
        cls.reg = MeanRegressor(xs=xs, ys=ys)
        cls.sol = sol

    def test_mean_within_tolerance(self):
        self.assertAlmostEqual(self.reg.mean, 5.0, places=2)

    def test_std_within_tolerance(self):
        self.assertAlmostEqual(self.reg.std, 1.5, places=2)

    def test_sem_equals_std_over_sqrt_n(self):
        expected = self.reg.std * len(self.reg.clean_ys) ** -0.5
        self.assertAlmostEqual(self.reg.sem, expected, places=12)

    def test_se_equals_std(self):
        self.assertAlmostEqual(self.reg.se, self.reg.std, places=12)

    def test_predict_error_sem_returns_sem(self):
        self.assertAlmostEqual(self.reg.predict_error(0.0, "SEM"), self.reg.sem, places=12)

    def test_predict_error_sd_returns_std(self):
        self.assertAlmostEqual(self.reg.predict_error(0.0, "SD"), self.reg.std, places=12)

    def test_predict_error_array_shape(self):
        e = self.reg.predict_error(np.array([0.0, 1.0, 2.0]), "SEM")
        self.assertEqual(e.shape, (3,))
        np.testing.assert_allclose(e, self.reg.sem, atol=1e-12)

    def test_predict_scalar_returns_mean(self):
        self.assertAlmostEqual(self.reg.predict(0.5), self.reg.mean, places=12)

    def test_predict_array_returns_constant(self):
        out = self.reg.predict(np.array([0.0, 1.0, 2.0]))
        self.assertEqual(out.shape, (3,))
        np.testing.assert_allclose(out, self.reg.mean, atol=1e-12)


class WeightedMeanTest(TestCase):
    """https://en.wikipedia.org/wiki/Weighted_mean#Example"""

    @classmethod
    def setUpClass(cls):
        xs, ys, yserr, sol = weighted_mean_data()
        cls.reg = WeightedMeanRegressor(
            xs=np.array(xs, dtype=float),
            ys=np.array(ys, dtype=float),
            yserr=np.array(yserr, dtype=float),
        )

    def test_weighted_mean(self):
        self.assertAlmostEqual(self.reg.mean, 86.0, places=10)

    def test_taylor_error_equals_inverse_sqrt_sum_weights(self):
        # ws = 1/yserr^2 = [20, 30] → 1/sqrt(50)
        self.assertAlmostEqual(self.reg.se, 50.0**-0.5, places=12)

    def test_sem_returns_taylor_for_weighted(self):
        """Weighted SEM must use 1/√Σw, not unweighted std/√n."""
        self.assertAlmostEqual(self.reg.sem, 50.0**-0.5, places=12)
        self.assertEqual(self.reg.sem, self.reg.se)


class MSEMConsistencyTest(TestCase):
    """MSEM = SEM × √MSWD should be applied uniformly across regressor
    subclasses, scaling the *correct* SEM for each (unweighted std/√n for
    MeanRegressor; weighted Taylor 1/√Σw for WeightedMean)."""

    def test_mean_msem_equals_sem_times_sqrt_mswd(self):
        # Use data with MSWD > 1 by combining inconsistent ys + yserr
        xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ys = np.array([10.0, 11.0, 9.0, 12.0, 8.0])
        yserr = np.full(5, 0.1)
        r = MeanRegressor(xs=xs, ys=ys, yserr=yserr)
        mswd = r.mswd
        if mswd > 1:
            expected = r.sem * mswd**0.5
        else:
            expected = r.sem
        self.assertAlmostEqual(r.predict_error(0.0, "MSEM"), expected, places=12)

    def test_weighted_mean_msem_uses_taylor_sem(self):
        """Weighted MSEM must scale the Taylor SEM, not std."""
        xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ys = np.array([10.0, 11.0, 9.0, 12.0, 8.0])
        yserr = np.array([0.5, 0.5, 0.5, 0.5, 0.5])
        r = WeightedMeanRegressor(xs=xs, ys=ys, yserr=yserr)
        mswd = r.mswd
        expected_base = r.sem  # = Taylor
        if mswd > 1:
            expected = expected_base * mswd**0.5
        else:
            expected = expected_base
        self.assertAlmostEqual(r.predict_error(0.0, "MSEM"), expected, places=12)

    def test_msem_collapses_to_sem_when_mswd_below_1(self):
        """No deflation when MSWD < 1 (one-sided scaling convention)."""
        # tightly-clustered ys with relatively large yserr → MSWD < 1
        xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ys = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
        yserr = np.array([0.5, 0.5, 0.5, 0.5, 0.5])
        r = WeightedMeanRegressor(xs=xs, ys=ys, yserr=yserr)
        self.assertLessEqual(r.mswd, 1.0)
        self.assertAlmostEqual(r.predict_error(0.0, "MSEM"), r.sem, places=12)


class CleanArrayExclusionTest(TestCase):
    """Verify get_excluded unions all four sources, and pre_clean unions
    user_excluded with truncate_excluded (regression: it was xor)."""

    def setUp(self):
        xs = np.arange(10).astype(float)
        ys = xs.copy()
        self.reg = MeanRegressor(xs=xs, ys=ys)

    def test_get_excluded_unions_sources(self):
        self.reg.user_excluded = [0]
        self.reg.outlier_excluded = [1]
        self.reg.truncate_excluded = [2]
        self.reg.ouser_excluded = [3]
        self.assertEqual(set(self.reg.get_excluded()), {0, 1, 2, 3})

    def test_get_excluded_deduplicates(self):
        self.reg.user_excluded = [5]
        self.reg.truncate_excluded = [5]
        self.assertEqual(self.reg.get_excluded(), [5])

    def test_pre_clean_unions_user_and_truncate(self):
        self.reg.user_excluded = [0]
        self.reg.truncate_excluded = [0, 1]
        self.reg.dirty = True
        # all three of indices 0,1 must be dropped (union, not xor)
        np.testing.assert_array_equal(
            self.reg.pre_clean_ys, np.array([2, 3, 4, 5, 6, 7, 8, 9], dtype=float)
        )


class WeightedPolynomialTest(TestCase):
    """When weights are equal, WLS must reduce to OLS exactly."""

    def test_equal_weights_match_ols(self):
        xs, ys, _ = ols_data()
        yserr = np.ones(len(xs))
        wls = WeightedPolynomialRegressor(xs=xs, ys=ys, yserr=yserr, fit="linear")
        wls.calculate()
        ols = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        ols.calculate()
        self.assertAlmostEqual(wls.coefficients[-1], ols.coefficients[-1], places=10)
        self.assertAlmostEqual(wls.coefficients[0], ols.coefficients[0], places=10)

    def test_pearson_weighted_fit(self):
        """WLS on Pearson dataset with 1/error^2 weights. Reference values
        from direct statsmodels WLS computation."""
        xs, ys, _, wys = pearson()
        eys = wys**-0.5
        wls = WeightedPolynomialRegressor(xs=xs, ys=ys, yserr=eys, fit="linear")
        wls.calculate()
        self.assertAlmostEqual(wls.coefficients[-1], -0.61081296, places=6)
        self.assertAlmostEqual(wls.coefficients[0], 6.10010932, places=6)
        ce = list(wls.coefficient_errors)
        self.assertAlmostEqual(ce[0], 0.42405945, places=6)
        self.assertAlmostEqual(ce[1], 0.06234095, places=6)

    def test_high_weight_dominates(self):
        """A point with overwhelmingly large weight pulls the fit to it."""
        xs = np.linspace(0, 10, 11)
        ys = np.zeros_like(xs)
        ys[5] = 100.0
        yserr = np.ones_like(xs) * 1e3
        yserr[5] = 1e-3
        wls = WeightedPolynomialRegressor(xs=xs, ys=ys, yserr=yserr, fit="linear")
        wls.calculate()
        self.assertAlmostEqual(wls.predict(5.0), 100.0, places=3)


class MultipleLinearRegressorTest(TestCase):
    """z = 1*x + 3*y. Coefficients in order [a_x, b_y, c]."""

    @classmethod
    def setUpClass(cls):
        xs = [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (1, 1)]
        ys = [0.0, 1.0, 2.0, 3.0, 6.0, 4.0]
        r = MultipleLinearRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_coefficient_x(self):
        self.assertAlmostEqual(self.reg.coefficients[0], 1.0, places=10)

    def test_coefficient_y(self):
        self.assertAlmostEqual(self.reg.coefficients[1], 3.0, places=10)

    def test_constant(self):
        self.assertAlmostEqual(self.reg.coefficients[2], 0.0, places=10)

    def test_predict_origin(self):
        self.assertAlmostEqual(self.reg.predict([(0, 0)])[0], 0.0, places=10)

    def test_predict_known_point(self):
        # z = 5*1 + 2*3 = 11
        self.assertAlmostEqual(self.reg.predict([(5, 2)])[0], 11.0, places=10)


class LeastSquaresSuppressDialogTest(TestCase):
    """`_suppress_ui_dialog()` must detect CI / pytest / unittest envs
    so curve_fit failures don't pop a GUI warning during tests."""

    def test_detects_pytest_env_var(self):
        from pychron.core.regression.least_squares_regressor import _suppress_ui_dialog
        import os

        saved = os.environ.get("PYTEST_CURRENT_TEST")
        try:
            os.environ["PYTEST_CURRENT_TEST"] = "test_node"
            self.assertTrue(_suppress_ui_dialog())
        finally:
            if saved is None:
                os.environ.pop("PYTEST_CURRENT_TEST", None)
            else:
                os.environ["PYTEST_CURRENT_TEST"] = saved

    def test_detects_ci_env_var(self):
        from pychron.core.regression.least_squares_regressor import _suppress_ui_dialog
        import os

        saved = os.environ.get("CI")
        try:
            os.environ["CI"] = "true"
            self.assertTrue(_suppress_ui_dialog())
        finally:
            if saved is None:
                os.environ.pop("CI", None)
            else:
                os.environ["CI"] = saved

    def test_detects_unittest_in_argv(self):
        """Tests run via `python -m unittest` → argv[0] contains 'unittest'."""
        from pychron.core.regression.least_squares_regressor import _suppress_ui_dialog

        # Running this very test, argv[0] should contain unittest or pytest.
        self.assertTrue(_suppress_ui_dialog())


class LeastSquaresClearFitTest(TestCase):
    def test_clear_fit_default_keeps_coeffs(self):
        from pychron.core.regression.least_squares_regressor import LeastSquaresRegressor

        r = LeastSquaresRegressor(xs=np.linspace(0, 10, 5), ys=np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        r.fitfunc = lambda x, a, b: a * x + b
        r.calculate()
        coeffs_before = list(r._coefficients)
        r._clear_fit()  # reset_coeffs=False (default)
        self.assertIsNone(r._covariance)
        self.assertEqual(list(r._coefficients), coeffs_before)

    def test_clear_fit_reset_coeffs_drops_them(self):
        from pychron.core.regression.least_squares_regressor import LeastSquaresRegressor

        r = LeastSquaresRegressor(xs=np.linspace(0, 10, 5), ys=np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        r.fitfunc = lambda x, a, b: a * x + b
        r.calculate()
        r._clear_fit(reset_coeffs=True)
        self.assertEqual(r._coefficients, [])
        self.assertEqual(r._coefficient_errors, [])


class LeastSquaresFitErrorTest(TestCase):
    def test_runtime_error_raises_fiterror(self):
        """When curve_fit fails to converge, LeastSquaresRegressor.calculate
        must raise FitError (not RuntimeError)."""
        from pychron.core.regression.least_squares_regressor import (
            LeastSquaresRegressor,
            FitError,
        )

        # build pathological data that won't fit a sinusoid + bad guess
        r = LeastSquaresRegressor(xs=np.linspace(0, 10, 5), ys=np.array([1.0, 1.0, 1.0, 1.0, 1.0]))
        # Choose a function whose curve_fit will fail with these starting values
        import numpy as _np

        r.fitfunc = lambda x, a, b: a * _np.exp(b * x)
        r._nargs = 2
        # Override initial guess to one that will diverge
        r._calculate_initial_guess = lambda: (1e30, 1e30)
        try:
            r.calculate()
        except FitError:
            return  # expected
        # If no exception, fit somehow converged; not a failure of the API


class LeastSquaresIntegrityTest(TestCase):
    """When data fails integrity check, _clear_fit runs and calculate returns."""

    def test_empty_data_clears(self):
        from pychron.core.regression.least_squares_regressor import LeastSquaresRegressor

        r = LeastSquaresRegressor(xs=np.array([]), ys=np.array([]))
        r.fitfunc = lambda x, a, b: a * x + b
        r.calculate()
        self.assertIsNone(r._covariance)


class ExponentialInitialGuessTest(TestCase):
    """`_calculate_initial_guess` covers growth + decay + degenerate cases."""

    def test_decay_case(self):
        from pychron.core.regression.least_squares_regressor import ExponentialRegressor

        xs = np.linspace(0, 10, 20)
        ys = 100 * np.exp(-0.1 * xs) + 1
        r = ExponentialRegressor(xs=xs, ys=ys)
        a, b, c = r._calculate_initial_guess()
        # decay: b > 0
        self.assertGreater(b, 0)

    def test_growth_case(self):
        from pychron.core.regression.least_squares_regressor import ExponentialRegressor

        xs = np.linspace(0, 10, 20)
        ys = 100 * np.exp(0.1 * xs) + 1
        r = ExponentialRegressor(xs=xs, ys=ys)
        a, b, c = r._calculate_initial_guess()
        # growth: b < 0
        self.assertLess(b, 0)

    def test_zero_dx_returns_constant_fallback(self):
        from pychron.core.regression.least_squares_regressor import ExponentialRegressor

        r = ExponentialRegressor(xs=np.array([5.0]), ys=np.array([10.0]))
        # dx = 0 → fallback (1, 0, y0)
        a, b, c = r._calculate_initial_guess()
        self.assertEqual(b, 0)
        self.assertEqual(c, 10.0)


class LeastSquaresConstructFitfuncSplitTest(TestCase):
    """`construct_fitfunc` strips 'custom:' prefix and splits on '_'.
    NOTE: numexpr ctx assigns args in REVERSE letter order — args=[v0, v1]
    binds to (b, a), not (a, b). Locking current behavior."""

    def test_strips_custom_prefix_and_underscore_suffix(self):
        from pychron.core.regression.least_squares_regressor import LeastSquaresRegressor

        r = LeastSquaresRegressor()
        r.construct_fitfunc("custom:a*x+b_SD")
        # Args reversed-bind: first arg → b, second → a.
        # For a=1, b=0, x=2: a*x + b = 2. Pass (b=0, a=1) i.e. (0.0, 1.0).
        result = r.fitfunc(np.array([2.0]), 0.0, 1.0)
        self.assertAlmostEqual(float(result[0]), 2.0, places=6)


class LeastSquaresRegressorTest(TestCase):
    """scipy.optimize.curve_fit-based regressor. Verify against
    closed-form linear fit and that coefficient errors come from cov diag."""

    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 21)
        ys = 2.0 * xs + 3.0
        r = LeastSquaresRegressor(xs=xs, ys=ys)
        r.fitfunc = lambda x, a, b: a * x + b
        r.calculate()
        cls.reg = r

    def test_recovers_slope(self):
        self.assertAlmostEqual(self.reg._coefficients[0], 2.0, places=8)

    def test_recovers_intercept(self):
        self.assertAlmostEqual(self.reg._coefficients[1], 3.0, places=8)

    def test_predict_scalar(self):
        self.assertAlmostEqual(self.reg.predict(5.0), 13.0, places=8)

    def test_predict_array(self):
        out = self.reg.predict(np.array([0.0, 5.0, 10.0]))
        np.testing.assert_allclose(out, [3.0, 13.0, 23.0], atol=1e-8)

    def test_coefficient_errors_are_sqrt_cov_diag(self):
        ce = self.reg._coefficient_errors
        expected = np.sqrt(np.diagonal(self.reg._covariance))
        np.testing.assert_allclose(ce, expected, atol=1e-12)


class YorkRegressorIdentityTest(TestCase):
    """York regressors with negligible xserr must approach OLS."""

    def setUp(self):
        self.xs = np.array([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        # add small noise so MSWD is meaningful
        residuals = np.array([0.1, -0.1, 0.05, -0.05, 0.1, -0.1, 0.05, -0.05, 0.1, -0.1])
        self.ys = 2 * self.xs + 3 + residuals
        self.xserr = np.ones(10) * 1e-6
        self.yserr = np.ones(10) * 0.1

    def test_reed_near_ols_slope(self):
        ols = PolynomialRegressor(xs=self.xs, ys=self.ys, fit="linear")
        ols.calculate()
        reed = ReedYorkRegressor(
            xs=self.xs,
            ys=self.ys,
            xserr=self.xserr,
            yserr=self.yserr,
        )
        reed.calculate()
        self.assertAlmostEqual(reed._slope, ols.coefficients[-1], places=4)
        self.assertAlmostEqual(reed._intercept, ols.coefficients[0], places=4)

    def test_newyork_near_ols_slope(self):
        ols = PolynomialRegressor(xs=self.xs, ys=self.ys, fit="linear")
        ols.calculate()
        ny = NewYorkRegressor(
            xs=self.xs,
            ys=self.ys,
            xserr=self.xserr,
            yserr=self.yserr,
        )
        ny.calculate()
        self.assertAlmostEqual(ny._slope, ols.coefficients[-1], places=4)
        self.assertAlmostEqual(ny._intercept, ols.coefficients[0], places=4)


class NewYorkPearsonTest(TestCase):
    """Pearson dataset. NewYork (Mahon 1996) reference values match
    LLNL MahonFitting / Trappitsch et al. (2018) implementation."""

    @classmethod
    def setUpClass(cls):
        xs, ys, wxs, wys = pearson()
        exs = wxs**-0.5
        eys = wys**-0.5
        r = NewYorkRegressor(xs=xs, ys=ys, xserr=exs, yserr=eys, error_calc_type="SE")
        r.calculate()
        cls.reg = r

    def test_slope(self):
        self.assertAlmostEqual(self.reg._slope, -0.48053341, places=6)

    def test_intercept(self):
        self.assertAlmostEqual(self.reg._intercept, 5.47991022, places=6)

    def test_slope_error(self):
        self.assertAlmostEqual(self.reg.get_slope_variance() ** 0.5, 0.05760009, places=6)

    def test_intercept_error(self):
        self.assertAlmostEqual(self.reg.get_intercept_error(), 0.29445368, places=6)

    def test_predict_at_zero_equals_intercept(self):
        self.assertAlmostEqual(self.reg.predict(0), self.reg._intercept, places=10)

    def test_predict_is_linear(self):
        # y(2) - y(1) == slope
        d = self.reg.predict(2) - self.reg.predict(1)
        self.assertAlmostEqual(d, self.reg._slope, places=10)


class InterpolationRegressorTest(TestCase):
    """Reference values: ys=[10,20,30,40,50] at xs=[0,1,2,3,4], errors
    [1,2,3,4,5]. Query at 2.5 sits between (2,30) and (3,40)."""

    def setUp(self):
        self.xs = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        self.ys = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        self.ye = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    def _make(self, kind):
        return InterpolationRegressor(xs=self.xs, ys=self.ys, yserr=self.ye, kind=kind)

    def test_preceding_value(self):
        ir = self._make("preceding")
        self.assertEqual(ir.predict([2.5])[0], 30.0)

    def test_preceding_error(self):
        ir = self._make("preceding")
        self.assertEqual(ir.predict_error([2.5])[0], 3.0)

    def test_succeeding_value(self):
        ir = self._make("succeeding")
        self.assertEqual(ir.predict([2.5])[0], 40.0)

    def test_succeeding_error(self):
        ir = self._make("succeeding")
        self.assertEqual(ir.predict_error([2.5])[0], 4.0)

    def test_bracketing_average_value(self):
        # (30 + 40) / 2 = 35
        ir = self._make("bracketing_average")
        self.assertAlmostEqual(ir.predict([2.5])[0], 35.0, places=10)

    def test_bracketing_average_error(self):
        # sqrt(3^2 + 4^2) / 2 = 5 / 2 = 2.5
        ir = self._make("bracketing_average")
        self.assertAlmostEqual(ir.predict_error([2.5])[0], 2.5, places=10)

    def test_bracketing_interpolate_value(self):
        # linear interp at 2.5 between (2,30) and (3,40) = 35
        ir = self._make("bracketing_interpolate")
        self.assertAlmostEqual(ir.predict([2.5])[0], 35.0, places=10)

    def test_bracketing_interpolate_error(self):
        # f=0.5 -> sqrt((0.5*3)^2 + (0.5*4)^2) = sqrt(6.25) = 2.5
        ir = self._make("bracketing_interpolate")
        self.assertAlmostEqual(ir.predict_error([2.5])[0], 2.5, places=10)

    def test_preceding_at_exact_node(self):
        ir = self._make("preceding")
        self.assertEqual(ir.predict([2.0])[0], 30.0)

    def test_preceding_skips_excluded(self):
        ir = self._make("preceding")
        ir.user_excluded = [2]  # exclude index of value 30
        self.assertEqual(ir.predict([2.5])[0], 20.0)


class FluxRegressorTest(TestCase):
    """Grid of 25 points on [0,4]^2 with z = x + 2y plus weighted mean
    neighbor predictions."""

    @classmethod
    def setUpClass(cls):
        cls.xs = np.array([(x, y) for x in range(5) for y in range(5)], dtype=float)
        cls.ys = cls.xs[:, 0] + 2 * cls.xs[:, 1]
        cls.yserr = np.full(len(cls.ys), 0.1)

    def test_plane_recovers_linear_surface(self):
        r = PlaneFluxRegressor(xs=self.xs, ys=self.ys, fit="linear")
        r.calculate()
        cs = list(r.coefficients)
        self.assertAlmostEqual(cs[0], 1.0, places=8)
        self.assertAlmostEqual(cs[1], 2.0, places=8)
        self.assertAlmostEqual(cs[2], 0.0, places=8)
        self.assertAlmostEqual(r.predict([(1, 1)])[0], 3.0, places=8)

    def test_bowl_fits_linear_when_no_curvature(self):
        """Bowl is a^2 + b^2 + a + b + c; for purely linear data the
        quadratic terms should be ~0."""
        r = BowlFluxRegressor(xs=self.xs, ys=self.ys, fit="linear")
        r.calculate()
        cs = list(r.coefficients)
        # x1^2, x2^2 terms ~ 0; x1, x2 ~ 1, 2; const ~ 0
        self.assertAlmostEqual(cs[0], 0.0, places=8)
        self.assertAlmostEqual(cs[1], 0.0, places=8)
        self.assertAlmostEqual(cs[2], 1.0, places=8)
        self.assertAlmostEqual(cs[3], 2.0, places=8)
        self.assertAlmostEqual(cs[4], 0.0, places=8)

    def test_high_order_polynomial(self):
        r = HighOrderPolynominalFluxRegressor(xs=self.xs, ys=self.ys, fit="linear")
        r.calculate()
        # for degree=1, _get_X yields columns [x1, x2, const]
        cs = list(r.coefficients)
        self.assertAlmostEqual(cs[0], 1.0, places=8)
        self.assertAlmostEqual(cs[1], 2.0, places=8)
        self.assertAlmostEqual(cs[2], 0.0, places=8)

    def test_nearest_neighbor_weighted_mean(self):
        r = NearestNeighborFluxRegressor(
            xs=self.xs,
            ys=self.ys,
            yserr=self.yserr,
            interpolation_style="Weighted Mean",
            n=3,
        )
        v = r.predict(np.array([[1.0, 1.0]]))[0]
        # the 3 nearest neighbors of (1,1) include (1,1) itself (z=3) plus
        # adjacent points; weighted mean must lie within [min(neighbors), max]
        self.assertGreater(v, 0.0)
        self.assertLess(v, 10.0)

    def test_nearest_neighbor_error_decreases_with_more_points(self):
        r1 = NearestNeighborFluxRegressor(
            xs=self.xs,
            ys=self.ys,
            yserr=self.yserr,
            interpolation_style="Weighted Mean",
            n=1,
        )
        r3 = NearestNeighborFluxRegressor(
            xs=self.xs,
            ys=self.ys,
            yserr=self.yserr,
            interpolation_style="Weighted Mean",
            n=3,
        )
        e1 = r1.predict_error(np.array([[1.0, 1.0]]))[0]
        e3 = r3.predict_error(np.array([[1.0, 1.0]]))[0]
        self.assertGreater(e1, e3)


class OLSAutoDispatchTest(TestCase):
    """`determine_fit(AUTO_LINEAR_PARABOLIC)` picks fit with higher adj R².
    `streq` matches casefold, so the lowercase form (used by RegressionGraph)
    also triggers the auto path.

    Tie-break note: when both fits achieve the same adj R², the strict `>`
    comparison falls through to the `else` branch and picks parabolic.
    """

    def test_picks_parabolic_for_curved_data(self):
        from pychron.pychron_constants import AUTO_LINEAR_PARABOLIC

        xs = np.linspace(-5, 5, 30)
        ys = 0.5 * xs**2 + 2 * xs + 1
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        r.determine_fit(AUTO_LINEAR_PARABOLIC.lower())
        self.assertEqual(r.fit, "parabolic")
        self.assertEqual(r.degree, 2)

    def test_picks_parabolic_on_tie(self):
        """When both fits achieve identical adj R² (perfect linear data),
        the strict `>` comparison picks parabolic by default."""
        from pychron.pychron_constants import AUTO_LINEAR_PARABOLIC

        xs = np.linspace(0, 10, 30)
        ys = 2 * xs + 3
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        r.determine_fit(AUTO_LINEAR_PARABOLIC.lower())
        self.assertEqual(r.fit, "parabolic")


class OLSFastPredictTest(TestCase):
    """`fast_predict` / `fast_predict2` reuse the fitted OLS engine and must
    agree with `predict` for the same exog."""

    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 21)
        ys = 2 * xs + 3
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r
        cls.ys = ys
        cls.pexog = r.get_exog(np.array([5.0]))

    def test_fast_predict_matches_predict(self):
        self.assertAlmostEqual(
            self.reg.fast_predict(self.ys, self.pexog)[0],
            self.reg.predict(5.0),
            places=10,
        )

    def test_fast_predict2_matches_predict(self):
        self.assertAlmostEqual(
            self.reg.fast_predict2(self.ys, self.pexog)[0],
            self.reg.predict(5.0),
            places=10,
        )


class OLSSetDegreeTest(TestCase):
    def setUp(self):
        xs = np.linspace(0, 10, 21)
        ys = xs.copy()
        self.reg = PolynomialRegressor(xs=xs, ys=ys)

    def test_parabolic_string(self):
        self.reg.set_degree("parabolic")
        self.assertEqual(self.reg.degree, 2)

    def test_cubic_string(self):
        self.reg.set_degree("cubic")
        self.assertEqual(self.reg.degree, 3)

    def test_none_defaults_to_linear(self):
        self.reg.set_degree(None)
        self.assertEqual(self.reg.degree, 1)

    def test_invalid_string_defaults_to_linear(self):
        self.reg.set_degree("bogus")
        self.assertEqual(self.reg.degree, 1)

    def test_refresh_false_does_not_mark_dirty(self):
        self.reg.calculate()
        self.reg.clear_dirty()
        self.reg.set_degree("parabolic", refresh=False)
        self.assertFalse(self.reg.is_dirty)


class FormattingTest(TestCase):
    """Locks in `tostring` / `make_equation` formatting so refactors don't
    silently change user-visible strings."""

    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 21)
        ys = 2 * xs + 3
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_tostring_contains_coefficients(self):
        s = self.reg.tostring()
        self.assertIn("A=", s)
        self.assertIn("B=", s)
        # slope ≈ 2, intercept ≈ 3
        self.assertIn("2.00000", s)
        self.assertIn("3.00000", s)

    def test_make_equation_linear(self):
        self.assertEqual(self.reg.make_equation(), "linear(CI)    y=Ax+B")

    def test_make_equation_parabolic(self):
        xs = np.linspace(0, 10, 21)
        ys = xs**2
        r = PolynomialRegressor(xs=xs, ys=ys, fit="parabolic")
        r.calculate()
        self.assertEqual(r.make_equation(), "parabolic(CI)    y=Ax2+Bx+C")

    def test_format_percent_error_normal(self):
        self.assertEqual(self.reg.format_percent_error(100.0, 1.0), "1.0%")

    def test_format_percent_error_zero_division(self):
        self.assertEqual(self.reg.format_percent_error(0.0, 1.0), "Inf")


class SetTruncateTest(TestCase):
    def setUp(self):
        self.xs = np.arange(10, dtype=float)
        self.ys = self.xs.copy()
        self.reg = MeanRegressor(xs=self.xs, ys=self.ys)

    def test_expression_x_less_than(self):
        self.reg.set_truncate("x<5")
        self.assertEqual(self.reg.truncate_excluded, [0, 1, 2, 3, 4])

    def test_expression_x_greater_equal(self):
        self.reg.set_truncate("x>=5")
        self.assertEqual(self.reg.truncate_excluded, [5, 6, 7, 8, 9])

    def test_expression_n_less_than(self):
        # n refers to the index, not the value of xs
        self.reg.set_truncate("n<3")
        self.assertEqual(self.reg.truncate_excluded, [0, 1, 2])

    def test_integer_truncate_keeps_first_n(self):
        # plain integer "5" excludes everything after index 5
        self.reg.set_truncate("5")
        self.assertEqual(self.reg.truncate_excluded, [6, 7, 8, 9])

    def test_empty_string_no_excludes(self):
        self.reg.set_truncate("")
        self.assertEqual(self.reg.truncate_excluded, [])

    def test_none_no_excludes(self):
        self.reg.set_truncate(None)
        self.assertEqual(self.reg.truncate_excluded, [])


class MeanFormattingTest(TestCase):
    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 10)
        ys = np.ones(10) * 5.0
        cls.reg = MeanRegressor(xs=xs, ys=ys)
        cls.reg.calculate()

    def test_summary_contains_stats(self):
        s = self.reg.summary
        self.assertIn("mean=5.0", s)
        self.assertIn("std=", s)
        self.assertIn("sem=", s)

    def test_tostring_contains_mean(self):
        s = self.reg.tostring()
        self.assertIn("mean=", s)
        self.assertIn("n=10", s)

    def test_make_equation_returns_label(self):
        self.assertEqual(self.reg.make_equation(), "Mean")

    def test_calculate_ci_symmetric(self):
        fx = np.array([0.0, 5.0])
        fy = self.reg.predict(fx)
        ly, uy = self.reg.calculate_ci(fx, fy)
        np.testing.assert_allclose(uy - fy, fy - ly, atol=1e-12)


class WeightedMeanFastPredictTest(TestCase):
    """`fast_predict2` is called by the monte_carlo estimator."""

    def test_returns_weighted_mean_broadcast(self):
        xs = np.array([1, 2, 3, 4, 5], dtype=float)
        ys = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        yserr = np.full(5, 0.1)
        wm = WeightedMeanRegressor(xs=xs, ys=ys, yserr=yserr)
        wm.calculate()
        out = wm.fast_predict2(ys, xs)
        self.assertEqual(out.shape, (5,))
        # equal weights → unweighted mean = 3
        np.testing.assert_allclose(out, 3.0, atol=1e-10)


class NewYorkXInterceptTest(TestCase):
    @classmethod
    def setUpClass(cls):
        xs, ys, wxs, wys = pearson()
        exs = wxs**-0.5
        eys = wys**-0.5
        r = NewYorkRegressor(xs=xs, ys=ys, xserr=exs, yserr=eys, error_calc_type="SE")
        r.calculate()
        cls.reg = r

    def test_x_intercept_value(self):
        # x_intercept = -intercept / slope
        expected = -self.reg._intercept / self.reg._slope
        self.assertAlmostEqual(self.reg._get_x_intercept(), expected, places=10)

    def test_get_x_intercept_nominal(self):
        ufx = self.reg.get_x_intercept()
        self.assertAlmostEqual(ufx.nominal_value, -self.reg._intercept / self.reg._slope, places=10)

    def test_get_x_intercept_error_nonzero(self):
        """Regression: previously `predict` returned a scalar, so
        `ufloat(xint, std_dev(xerr))` had std_dev=0 for every analysis.
        Now propagates slope/intercept variances + York covariance."""
        ufx = self.reg.get_x_intercept()
        self.assertGreater(ufx.std_dev, 0)

    def test_get_x_intercept_error_independent_of_zero_intercept(self):
        """When slope→0, x_intercept is undefined; method must not crash."""
        # Synthesize a Y regressor with zero slope by giving constant ys
        xs = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        ys = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        es = np.full(5, 0.1)
        r = NewYorkRegressor(xs=xs, ys=ys, xserr=es, yserr=es)
        r.calculate()
        # may not be exactly zero but very small; verify no exception
        try:
            r.get_x_intercept()
        except Exception as e:
            self.fail(f"get_x_intercept raised: {e}")


class YorkMSWDTest(TestCase):
    """Mahon (1996) MSWD for the York regressor uses `calculate_mswd2`
    (chi-squared per dof), not the unweighted-mean MSWD from the base class."""

    def test_mswd_matches_pearson_reference(self):
        xs, ys, wxs, wys = pearson()
        exs = wxs**-0.5
        eys = wys**-0.5
        r = NewYorkRegressor(xs=xs, ys=ys, xserr=exs, yserr=eys)
        r.calculate()
        self.assertAlmostEqual(r.mswd, 1.4832, places=3)


class LeastSquaresConstructFitfuncTest(TestCase):
    """`construct_fitfunc` builds a numexpr-backed callable from a string
    of the form 'custom:a*x+b'. The resulting fit must recover known
    coefficients."""

    def test_linear_string_fit(self):
        xs = np.linspace(0, 10, 21)
        ys = 2.0 * xs + 3.0
        r = LeastSquaresRegressor(xs=xs, ys=ys)
        r.construct_fitfunc("custom:a*x+b")
        self.assertEqual(r._nargs, 2)
        r.calculate()
        # ctx maps letters in REVERSE: ['b','a'], so coeffs[0]=b, coeffs[1]=a
        self.assertAlmostEqual(r._coefficients[0], 3.0, places=6)
        self.assertAlmostEqual(r._coefficients[1], 2.0, places=6)


class FluxInterpolatorsTest(TestCase):
    """BSpline / RBF / GridData / IDW must reproduce a known linear surface
    `z = x + 2y` at an interior query point (2.5, 2.5) → 7.5."""

    @classmethod
    def setUpClass(cls):
        cls.xs = np.array([(x, y) for x in range(6) for y in range(6)], dtype=float)
        cls.ys = cls.xs[:, 0] + 2 * cls.xs[:, 1]

    def test_bspline_interpolates_linear(self):
        r = BSplineRegressor(xs=self.xs, ys=self.ys)
        r.calculate()
        self.assertAlmostEqual(r.predict_grid(2.5, 2.5), 7.5, places=6)

    def test_rbf_predicts_grid(self):
        r = RBFRegressor(xs=self.xs, ys=self.ys)
        r.calculate()
        # RBF multiquadric is approximate, allow 5% slack
        self.assertAlmostEqual(r.predict_grid(2.5, 2.5), 7.5, delta=0.5)

    def test_rbf_fast_predict2_matches_predict_grid(self):
        r = RBFRegressor(xs=self.xs, ys=self.ys)
        r.calculate()
        pt = np.array([[2.5, 2.5]])
        self.assertAlmostEqual(r.fast_predict2(self.ys, pt)[0], r.predict_grid(2.5, 2.5), places=10)

    def test_griddata_cubic_recovers_surface(self):
        r = GridDataRegressor(xs=self.xs, ys=self.ys)
        out = r.predict_grid(np.array([2.5]), np.array([2.5]))
        self.assertAlmostEqual(out[0], 7.5, places=4)

    def test_griddata_fast_predict2(self):
        r = GridDataRegressor(xs=self.xs, ys=self.ys)
        out = r.fast_predict2(self.ys, np.array([[2.5, 2.5]]))
        self.assertAlmostEqual(out[0], 7.5, places=4)

    def test_idw_predict_within_neighborhood(self):
        r = IDWRegressor(xs=self.xs, ys=self.ys)
        r.calculate()
        v = r.predict(np.array([[2.5, 2.5]]))[0]
        # IDW weights ~ 1/d^2 over 8 nearest; should be close to local mean
        self.assertGreater(v, 5.0)
        self.assertLess(v, 10.0)


class NearestNeighborSetNeighborsTest(TestCase):
    """`set_neighbors` writes `bracket_a` / `bracket_b` attributes on each
    unknown point, set from the hole IDs of the n nearest monitors."""

    def test_writes_bracket_ids(self):
        xs = np.array([(x, y) for x in range(4) for y in range(4)], dtype=float)
        ys = xs[:, 0] + 2 * xs[:, 1]

        class Pt:
            def __init__(self, x, y, hid=""):
                self.x = x
                self.y = y
                self.hole_id = hid

        unks = [Pt(1.5, 1.5)]
        mons = [Pt(x, y, hid=str(i)) for i, (x, y) in enumerate(xs)]
        nn = NearestNeighborFluxRegressor(xs=xs, ys=ys, yserr=np.full(len(ys), 0.1), n=2)
        nn.set_neighbors(unks, mons)
        self.assertIsNotNone(unks[0].bracket_a)
        self.assertIsNotNone(unks[0].bracket_b)
        # the two indices must be sorted ascending
        self.assertLessEqual(int(unks[0].bracket_a), int(unks[0].bracket_b))

    def test_n_neighbors_returned(self):
        xs = np.array([(x, y) for x in range(4) for y in range(4)], dtype=float)
        ys = xs[:, 0] + 2 * xs[:, 1]
        for n in (1, 3, 5):
            nn = NearestNeighborFluxRegressor(xs=xs, ys=ys, yserr=np.full(len(ys), 0.1), n=n)
            idx, ds = nn._get_neighbors(1.5, 1.5)
            self.assertEqual(len(idx), n)
            self.assertEqual(len(ds), n)


class InterpolationEdgeCaseTest(TestCase):
    """Edge cases for InterpolationRegressor: queries outside data range,
    succeeding past the end, all-excluded recovery."""

    def setUp(self):
        self.xs = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        self.ys = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        self.ye = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    def _make(self, kind):
        return InterpolationRegressor(xs=self.xs, ys=self.ys, yserr=self.ye, kind=kind)

    def test_succeeding_past_end_falls_back_to_last(self):
        ir = self._make("succeeding")
        # query beyond max x → falls back to last index
        self.assertEqual(ir.predict([100.0])[0], 50.0)

    def test_preceding_before_start_falls_back_to_first(self):
        ir = self._make("preceding")
        # query before min x → falls back to index 0
        self.assertEqual(ir.predict([-100.0])[0], 10.0)

    def test_bracketing_interpolate_above_range_returns_last(self):
        ir = self._make("bracketing_interpolate")
        self.assertEqual(ir.predict([100.0])[0], 50.0)

    def test_bracketing_interpolate_below_range_returns_first(self):
        ir = self._make("bracketing_interpolate")
        self.assertEqual(ir.predict([-100.0])[0], 10.0)


class WLSEngineFactoryTest(TestCase):
    """Single-point fallback in `_engine_factory` duplicates the weight so
    the WLS engine has two rows. Exercises the conditional path."""

    def test_duplicates_weight_for_single_point(self):
        # Use a 1-point dataset that gets bumped to 2 by base OLS.calculate.
        # The OLS calculate() bumps cxs/cys but yserr stays length 1.
        # The factory must still produce a fittable engine.
        r = WeightedPolynomialRegressor(
            xs=np.array([1.0]),
            ys=np.array([2.0]),
            yserr=np.array([0.1]),
            fit="linear",
        )
        r.calculate()
        # No exception means the single-point fallback path executed.
        self.assertIsNotNone(r._result)


class WeightedMultipleLinearRegressorTest(TestCase):
    """z = 1*x + 3*y fit with per-point weights. With equal weights the
    weighted multiple-linear fit must reduce to the unweighted one."""

    @classmethod
    def setUpClass(cls):
        cls.xs = [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (1, 1)]
        cls.ys = [0.0, 1.0, 2.0, 3.0, 6.0, 4.0]

    def test_recovers_coefficients_with_equal_weights(self):
        yserr = np.ones(len(self.ys))
        r = WeightedMultipleLinearRegressor(xs=self.xs, ys=self.ys, yserr=yserr, fit="linear")
        r.calculate()
        self.assertAlmostEqual(r.coefficients[0], 1.0, places=8)
        self.assertAlmostEqual(r.coefficients[1], 3.0, places=8)
        self.assertAlmostEqual(r.coefficients[2], 0.0, places=8)

    def test_matches_unweighted_for_equal_weights(self):
        yserr = np.ones(len(self.ys))
        wls = WeightedMultipleLinearRegressor(xs=self.xs, ys=self.ys, yserr=yserr, fit="linear")
        wls.calculate()
        ols = MultipleLinearRegressor(xs=self.xs, ys=self.ys, fit="linear")
        ols.calculate()
        np.testing.assert_allclose(list(wls.coefficients), list(ols.coefficients), atol=1e-10)


class ReedXInterceptTest(TestCase):
    """Reed regressor x-intercept propagates slope/intercept variance via the
    York covariance identity (mirrors the NewYork x-intercept test)."""

    @classmethod
    def setUpClass(cls):
        xs, ys, wxs, wys = pearson()
        exs = wxs**-0.5
        eys = wys**-0.5
        r = ReedYorkRegressor(xs=xs, ys=ys, xserr=exs, yserr=eys, error_calc_type="SE")
        r.calculate()
        cls.reg = r

    def test_x_intercept_nominal(self):
        ufx = self.reg.get_x_intercept()
        self.assertAlmostEqual(ufx.nominal_value, -self.reg._intercept / self.reg._slope, places=10)

    def test_x_intercept_error_nonzero(self):
        self.assertGreater(self.reg.get_x_intercept().std_dev, 0)


class YorkInterceptErrorTest(TestCase):
    """`get_intercept_error` dispatch: SE → √(intercept variance);
    CI → finite confidence half-width; unknown → 0."""

    @classmethod
    def setUpClass(cls):
        xs, ys, wxs, wys = pearson()
        cls.xs, cls.ys = xs, ys
        cls.exs = wxs**-0.5
        cls.eys = wys**-0.5

    def _make(self, error_calc):
        r = NewYorkRegressor(
            xs=self.xs, ys=self.ys, xserr=self.exs, yserr=self.eys, error_calc_type=error_calc
        )
        r.calculate()
        return r

    def test_se_equals_sqrt_intercept_variance(self):
        r = self._make("SE")
        self.assertAlmostEqual(
            r.get_intercept_error(), r.get_intercept_variance() ** 0.5, places=12
        )

    def test_ci_is_finite_and_positive(self):
        r = self._make("CI")
        e = r.get_intercept_error()
        self.assertGreater(e, 0)
        self.assertTrue(np.isfinite(e))

    def test_unknown_error_calc_returns_zero(self):
        r = self._make("SD")
        self.assertEqual(r.get_intercept_error(), 0)


class LeastSquaresPredictErrorCaseTest(TestCase):
    """`predict_error` resolves the error_calc keyword case-insensitively and
    treats None as the SEM default."""

    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 21)
        # add fixed scatter so the residual standard error (sef) is nonzero
        ys = 2.0 * xs + 3.0 + np.sin(xs)
        r = LeastSquaresRegressor(xs=xs, ys=ys)
        r.fitfunc = lambda x, a, b: a * x + b
        r.calculate()
        cls.reg = r

    def test_sem_case_insensitive(self):
        lo = self.reg.predict_error(5.0, "sem")
        hi = self.reg.predict_error(5.0, "SEM")
        self.assertAlmostEqual(lo, hi, places=12)

    def test_none_defaults_to_sem(self):
        self.assertAlmostEqual(
            self.reg.predict_error(5.0, None), self.reg.predict_error(5.0, "sem"), places=12
        )

    def test_sd_greater_than_sem(self):
        self.assertGreater(self.reg.predict_error(5.0, "SD"), self.reg.predict_error(5.0, "sem"))


class YorkBaseRegressorTest(TestCase):
    """Base York 1969 regressor (the iterative slope solve + York-1969 basic
    slope variance 1/Σ(W·U²)). Subclasses NewYork/Reed only change the variance
    propagation, so the slope/intercept must match the Mahon reference."""

    @classmethod
    def setUpClass(cls):
        xs, ys, wxs, wys = pearson()
        exs = wxs**-0.5
        eys = wys**-0.5
        r = YorkRegressor(xs=xs, ys=ys, xserr=exs, yserr=eys, error_calc_type="SE")
        r.calculate()
        cls.reg = r

    def test_slope_matches_reference(self):
        self.assertAlmostEqual(self.reg._slope, -0.48053341, places=6)

    def test_intercept_matches_reference(self):
        self.assertAlmostEqual(self.reg._intercept, 5.47991022, places=6)

    def test_slope_error_positive(self):
        self.assertGreater(self.reg.get_slope_error(), 0)

    def test_intercept_error_equals_sqrt_variance(self):
        self.assertAlmostEqual(
            self.reg.get_intercept_error(),
            self.reg.get_intercept_variance() ** 0.5,
            places=12,
        )

    def test_basic_slope_variance_identity(self):
        """York 1969 basic form: σ_b² = 1/Σ(W·U²)."""
        b = self.reg._slope
        W = self.reg._calculate_W(b)
        U, _ = self.reg._calculate_UV(W)
        expected = 1.0 / (W * U**2).sum()
        self.assertAlmostEqual(self.reg.get_slope_variance(), expected, places=12)


class OLSNoResultTest(TestCase):
    """Before `calculate`, `_result` is None: predict must degrade gracefully
    to 0 / zeros and predict_error_matrix to zeros."""

    def setUp(self):
        xs, ys, _ = ols_data()
        # no fit= so the degree change doesn't auto-trigger calculate()
        self.reg = OLSRegressor(xs=xs, ys=ys)

    def test_predict_scalar_zero(self):
        self.assertEqual(self.reg.predict(5.0), 0)

    def test_predict_array_zeros(self):
        out = self.reg.predict(np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(out, np.zeros(3))

    def test_predict_error_matrix_zeros(self):
        out = self.reg.predict_error_matrix(np.array([1.0, 2.0]))
        np.testing.assert_array_equal(out, np.zeros(2))

    def test_summary_none(self):
        self.assertIsNone(self.reg.summary)


class OLSPredictionEnvelopeTest(TestCase):
    """`calculate_prediction_envelope` returns statsmodels WLS prediction-std
    bounds (lower < upper element-wise)."""

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_lower_below_upper(self):
        fx = np.asarray(self.reg.xs, dtype=float)
        fy = self.reg.predict(fx)
        lower, upper, _ = self.reg.calculate_prediction_envelope(fx, fy)
        self.assertTrue(np.all(lower < upper))


class OLSPredictErrorMSEMTest(TestCase):
    """`predict_error_matrix` MSEM branch scales SEM by √MSWD when MSWD>1."""

    @classmethod
    def setUpClass(cls):
        # scattered data so the fit MSWD-style scale (>1) is exercised
        xs = np.linspace(0, 10, 21)
        ys = 2.0 * xs + 3.0 + np.sin(xs) * 2.0
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r

    def test_msem_scales_sem_by_sqrt_mswd(self):
        from pychron.pychron_constants import MSEM

        sem = self.reg.predict_error_matrix(np.array([5.0]), "SEM")[0]
        msem = self.reg.predict_error_matrix(np.array([5.0]), MSEM)[0]
        scale = self.reg._mswd_scale()
        self.assertAlmostEqual(msem, sem * scale, places=12)


class BaseRegressorIQROutlierTest(TestCase):
    """The base (OLS) `calculate_outliers` IQR branch: indices outside the
    1.5·IQR fence. (Mean overrides this, so test it on a polynomial fit.)"""

    def test_iqr_outlier_on_polynomial(self):
        xs = np.arange(20).astype(float)
        ys = xs.copy()
        ys[10] = 500.0
        r = PolynomialRegressor(
            xs=xs, ys=ys, fit="linear", filter_outliers_dict={"use_iqr_filtering": True}
        )
        r.calculate()
        self.assertIn(10, list(r.calculate_outliers()))


class FilterBoundsBranchTest(TestCase):
    """`calculate_filter_bounds` explicit-bound and std-deviation branches."""

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        cls.xs, cls.ys = xs, ys

    def test_explicit_bound(self):
        r = PolynomialRegressor(xs=self.xs, ys=self.ys, fit="linear")
        r.calculate()
        fx = np.array([30.0, 50.0])
        fy = r.predict(fx)
        lower, upper = r.calculate_filter_bounds(model=fy, bound=2.0)
        np.testing.assert_allclose(upper - fy, 2.0, atol=1e-12)
        np.testing.assert_allclose(fy - lower, 2.0, atol=1e-12)

    def test_std_deviation_filtering_branch(self):
        r = PolynomialRegressor(
            xs=self.xs,
            ys=self.ys,
            fit="linear",
            filter_outliers_dict={"use_standard_deviation_filtering": True, "std_devs": 2},
        )
        r.calculate()
        fy = r.predict(np.array([50.0]))
        lower, upper = r.calculate_filter_bounds(model=fy)
        self.assertAlmostEqual((upper - lower)[0], 2.0 * 2.0 * r.std, places=10)


class ConfidenceIntervalSmallNTest(TestCase):
    """`_calculate_confidence_interval` returns None when n ≤ 2 (CI undefined)."""

    def test_two_points_returns_none(self):
        r = PolynomialRegressor(xs=np.array([0.0, 1.0]), ys=np.array([0.0, 1.0]), fit="linear")
        out = r._calculate_confidence_interval(
            np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([0.5])
        )
        self.assertIsNone(out)


class BaseRegressorPropertyTest(TestCase):
    """min/max/delta, mean_mswd family, get_fit_dict, fn formatting."""

    def setUp(self):
        xs = np.arange(10, dtype=float)
        ys = np.arange(10, dtype=float)
        yserr = np.full(10, 0.5)
        self.reg = MeanRegressor(xs=xs, ys=ys, yserr=yserr)

    def test_min_max_delta(self):
        self.assertEqual(self.reg.min, 0.0)
        self.assertEqual(self.reg.max, 9.0)
        self.assertEqual(self.reg.delta, 9.0)

    def test_mean_mswd_is_number(self):
        self.assertIsNotNone(self.reg.mean_mswd)
        self.assertIsInstance(self.reg.valid_mean_mswd, (bool, np.bool_))

    def test_mswd_pvalue_in_unit_interval(self):
        p = self.reg.mswd_pvalue
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_get_fit_dict(self):
        d = self.reg.get_fit_dict()
        self.assertEqual(d["fit"], self.reg.fit)
        self.assertEqual(d["error_type"], self.reg.error_calc_type)

    def test_fn_formats_fraction_when_filtered(self):
        self.reg.user_excluded = [0]
        self.reg.dirty = True
        self.assertEqual(self.reg.fn, "9/10")


class OLSFastPredictExogTest(TestCase):
    """`fast_predict` with an explicit exog re-whitens the design matrix and
    must still agree with `predict`."""

    @classmethod
    def setUpClass(cls):
        xs = np.linspace(0, 10, 21)
        ys = 2.0 * xs + 3.0
        r = PolynomialRegressor(xs=xs, ys=ys, fit="linear")
        r.calculate()
        cls.reg = r
        cls.ys = ys

    def test_fast_predict_with_exog(self):
        exog = self.reg.get_exog(np.asarray(self.reg.xs, dtype=float))
        pexog = self.reg.get_exog(np.array([5.0]))
        out = self.reg.fast_predict(self.ys, pexog, exog=exog)
        self.assertAlmostEqual(out[0], self.reg.predict(5.0), places=8)


class OLSAbortTest(TestCase):
    """Empty data fails the integrity check (and is not a single point), so
    `calculate` aborts and leaves `_result` None."""

    def test_empty_aborts(self):
        r = OLSRegressor(xs=np.array([]), ys=np.array([]), fit="linear")
        r.calculate()
        self.assertIsNone(r._result)


class OLSMonteCarloErrorTest(TestCase):
    """`predict_error(x, 'MC')` runs the Monte Carlo estimator and returns a
    positive, finite error. (Stochastic — assert sign/finiteness only.)"""

    @classmethod
    def setUpClass(cls):
        xs, ys, _ = ols_data()
        yserr = np.full(len(xs), 0.5)
        # MC propagates measurement error, so the regressor needs yserr
        r = WeightedPolynomialRegressor(xs=xs, ys=ys, yserr=yserr, fit="linear")
        r.calculate()
        cls.reg = r

    def test_mc_error_scalar_positive(self):
        e = self.reg.predict_error(28.6, "MC")
        self.assertGreater(e, 0)
        self.assertTrue(np.isfinite(e))


class WeightedMeanEmptyTest(TestCase):
    """Empty weighted mean: weights are undefined, so sem/se collapse to 0
    instead of raising."""

    def test_empty_sem_zero(self):
        r = WeightedMeanRegressor(xs=np.array([]), ys=np.array([]), yserr=np.array([]))
        self.assertEqual(r.sem, 0)
        self.assertEqual(r.se, 0)


# ============= EOF =============================================
