# ===============================================================================
# Copyright 2012 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================

# ============= enthought library imports =======================
import os
import string
import sys

from numpy import asarray, diagonal, exp, isscalar, log, sqrt, zeros
from scipy import optimize
from traits.api import Callable, List

from pychron.core.regression.base_regressor import BaseRegressor


class FitError(BaseException):
    pass


def _suppress_ui_dialog():
    """Don't open a UI dialog from inside test or CI runs."""
    if os.getenv("TRAVIS_CI") or os.getenv("CI") or os.getenv("PYTEST_CURRENT_TEST"):
        return True
    # detect unittest / pytest invocation
    argv0 = (sys.argv[0] or "").lower()
    return "unittest" in argv0 or "pytest" in argv0 or "_test" in argv0


class LeastSquaresRegressor(BaseRegressor):
    fitfunc = Callable
    initial_guess = List

    _covariance = None
    _nargs = 2

    def construct_fitfunc(self, fitstr):
        fitstr = fitstr.lstrip("custom:").lower().split("_")[0]
        import numexpr as ne

        def func(x, *args):
            ctx = dict(zip(string.ascii_lowercase[: len(args)][::-1], args))
            ctx["x"] = x
            return ne.evaluate(fitstr, local_dict=ctx)

        self._nargs = 2
        self.fitfunc = func

    def calculate(self, filtering=False):
        cxs = self.pre_clean_xs
        cys = self.pre_clean_ys

        if not self._check_integrity(cxs, cys):
            self._clear_fit()
            return

        if filtering:
            fx, fy = cxs, cys
        else:
            fx, fy = self.calculate_filtered_data()

        try:
            coeffs, cov = optimize.curve_fit(
                self.fitfunc, fx, fy, p0=self._calculate_initial_guess()
            )
        except RuntimeError:
            self._clear_fit(reset_coeffs=True)
            if not _suppress_ui_dialog():
                from pyface.message_dialog import warning

                warning(None, "Exponential failed to converge. Choose a different fit")
            raise FitError()

        self._coefficients = list(coeffs)
        self._covariance = cov
        self._coefficient_errors = list(sqrt(diagonal(cov)))
        self.clear_dirty()

    def _clear_fit(self, reset_coeffs=False):
        self._covariance = None
        if reset_coeffs:
            self._coefficients = []
            self._coefficient_errors = []
        self.clear_dirty()

    def _calculate_initial_guess(self):
        return zeros(self._nargs)

    def _calculate_coefficients(self):
        return self._coefficients

    def _calculate_coefficient_errors(self):
        return self._coefficient_errors

    def predict(self, x):
        return_single = isscalar(x)
        x = asarray([x]) if return_single else asarray(x)
        out = self.fitfunc(x, *self._coefficients)
        return out[0] if return_single else out

    def predict_error(self, x, error_calc="sem"):
        """
        Returns the predicted error in y.

        varY_hat_i = Xk_i @ cov @ Xk_i^T, where Xk_i = [xi, xi, ..., xi] (length n_params).
        Vectorized across all xi via (Xk @ cov * Xk).sum(axis=1).
        """
        return_single = isscalar(x)
        x = asarray([x] if return_single else x, dtype=float)

        sef = self.calculate_standard_error_fit()
        cov = asarray(self._covariance)
        n_params = cov.shape[0]
        # Broadcast each xi into a row of length n_params.
        Xk = x[:, None].repeat(n_params, axis=1)
        varY_hat = (Xk.dot(cov) * Xk).sum(axis=1)

        if error_calc == "sem":
            out = sef * sqrt(varY_hat)
        else:
            # SD: sqrt(sef^2 + sef^2 * varY_hat) = sef * sqrt(1 + varY_hat)
            out = sef * sqrt(1.0 + varY_hat)

        return out[0] if return_single else out


class ExponentialRegressor(LeastSquaresRegressor):
    def __init__(self, *args, **kw):
        def fitfunc(x, a, b, c):
            return a * exp(-b * x) + c

        self.fitfunc = fitfunc
        super(ExponentialRegressor, self).__init__(*args, **kw)

    _nargs = 3

    def _calculate_initial_guess(self):
        """
        Data-driven guess for `a*exp(-b*x) + c`.

        Approximation:
          c ≈ asymptote (≈ ys[-1] for decay, ys[0] for growth)
          a ≈ ys[0] - c
          b ≈ -log((ys[-1] - c) / a) / (xs[-1] - xs[0])

        Previously hard-coded (100, 0.1, -100) / (-10, 0.1, 10). Those
        guesses failed `curve_fit` for any data whose scale or sign
        diverged from the constants, including the test suite's growth
        case `a*exp(0.05x) + 1`.
        """
        ys = asarray(self.ys, dtype=float)
        xs = asarray(self.xs, dtype=float)
        y0, yN = ys[0], ys[-1]
        dx = xs[-1] - xs[0]
        if dx == 0:
            return 1.0, 0.0, float(y0)

        decay = y0 > yN
        if decay:
            c = min(yN, 0.0)
        else:
            c = min(y0, 0.0)
        a = y0 - c
        num = yN - c
        # avoid log of <=0 by guarding ratio
        if a == 0 or num <= 0 or (num / a) <= 0:
            return (1.0, 0.1 if decay else -0.1, float(c))
        b = -log(num / a) / dx
        return float(a), float(b), float(c)


# ============= EOF =============================================
