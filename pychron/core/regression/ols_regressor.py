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
import logging

from numpy import (
    asarray,
    atleast_1d,
    column_stack,
    dot,
    hstack,
    isscalar,
    linalg,
    ones_like,
    sqrt,
    vander,
    zeros_like,
)
from statsmodels.api import OLS
from traits.api import Int, Property

# ============= local library imports  ==========================
from pychron.core.helpers.fits import FITS, fit_to_degree
from pychron.core.helpers.strtools import streq
from pychron.core.regression.base_regressor import BaseRegressor
from pychron.pychron_constants import MSEM, SEM, AUTO_LINEAR_PARABOLIC

logger = logging.getLogger("Regressor")


class OLSRegressor(BaseRegressor):
    degree = Property(depends_on="_degree")
    _degree = Int
    constant = None
    _ols = None

    def set_degree(self, d, refresh=True):
        if isinstance(d, str):
            self._fit = d
            try:
                d = fit_to_degree(d)
            except ValueError:
                d = 1

        if d is None:
            d = 1

        if refresh:
            self.dirty = True
            self._degree = d
        else:
            self.trait_setq(_degree=d)

    def get_exog(self, x):
        return self._get_X(x)

    def fast_predict(self, endog, pexog, exog=None):
        ols = self._ols
        ols.wendog = ols.whiten(endog)

        if exog is not None:
            ols.wexog = ols.whiten(exog)

            # force recalculation
            del ols.pinv_wexog

        result = ols.fit()
        return result.predict(pexog)

    def fast_predict2(self, endog, exog):
        """
        this function is less flexible than fast_predict but is 2x faster. it doesn't use RegressionResults class
        simple does the lin algebra to predict values.

        currently useful for monte_carlo_estimation
        """
        if not hasattr(self, "pinv_wexog"):
            self.pinv_wexog = linalg.pinv(self._ols.wexog)

        beta = dot(self.pinv_wexog, endog)

        return dot(exog, beta)

    def determine_fit(self, fit):
        if isinstance(fit, str) and streq(fit, AUTO_LINEAR_PARABOLIC):
            self.set_degree("linear", refresh=False)
            self.calculate()
            linear_r = self.rsquared_adj

            self.set_degree("parabolic", refresh=False)
            self.calculate()
            parabolic_r = self.rsquared_adj

            if linear_r > parabolic_r:
                self.fit = "linear"
                self.set_degree("linear")
            else:
                self.fit = "parabolic"
                self.set_degree("parabolic")

        return self.fit

    def calculate(self, filtering=False):
        cxs = self.clean_xs
        cys = self.clean_ys

        integrity_check = True
        if not self._check_integrity(cxs, cys, verbose=True):
            # Single point: duplicate it so the engine has 2 rows to fit.
            if len(cxs) == 1 and len(cys) == 1:
                cxs = hstack((cxs, cxs[0]))
                cys = hstack((cys, cys[0]))
                integrity_check = False
            else:
                self._abort_calculate("A integrity check failed")
                return

        if integrity_check and not filtering:
            fx, fy = self.calculate_filtered_data()
        else:
            fx, fy = cxs, cys

        X = self._get_X(fx)
        if integrity_check and not self._check_integrity(X, fy):
            self._abort_calculate("B integrity check failed")
            return

        ols = self._engine_factory(fy, X, check_integrity=integrity_check)
        if ols is None:
            self._abort_calculate("engine factory returned None")
            return

        self._ols = ols
        self._result = ols.fit()
        self.clear_dirty()

    def _abort_calculate(self, reason):
        self._result = None
        self.clear_dirty()
        logger.debug(reason)

    def calculate_prediction_envelope(self, fx, fy):
        from statsmodels.sandbox.regression.predstd import wls_prediction_std

        prstd, iv_l, iv_u = wls_prediction_std(self._result)
        return iv_l, iv_u, self._result.model.exog[::, 1]

    def predict(self, pos):
        return_single = isscalar(pos)
        pos = atleast_1d(asarray(pos))

        res = self._result
        if res is None:
            return 0 if return_single else zeros_like(pos)

        pred = res.predict(self._get_X(xs=pos))
        return pred[0] if return_single else pred

    def predict_error(self, x, error_calc=None):
        if error_calc is None:
            error_calc = self.error_calc_type

        return_single = isscalar(x)
        x = atleast_1d(asarray(x))

        if not error_calc or error_calc == "CI":
            e = self.calculate_ci_error(x)
        elif error_calc == "MC":
            e = self.calculate_mc_error(x)
        else:
            e = self.predict_error_matrix(x, error_calc)

        if return_single:
            try:
                return e[0]
            except TypeError:
                return 0
        return e

    def predict_error_matrix(self, x, error_calc="SEM"):
        """
        Predict the error in y using matrix math.
        Draper & Smith chapter 2.4 page 56.

        For each xi, varY_hat = Xk @ covarM @ Xk.T where Xk = [1, xi, xi^2, ...].
        Vectorized across all xi via the row-wise diagonal:
            varY_hat = ((Xk @ covarM) * Xk).sum(axis=1)
        """
        if self._result is None:
            return zeros_like(x)

        x = asarray(x)
        sef = self.calculate_standard_error_fit()
        covarM = asarray(self.var_covar)

        Xk = self._get_X(xs=x)
        varY_hat = (Xk.dot(covarM) * Xk).sum(axis=1)

        ec = error_calc.lower()
        if ec == SEM.lower():
            return sef * sqrt(varY_hat)
        if ec == MSEM.lower():
            return sef * sqrt(varY_hat) * self._mswd_scale()
        # SD: sqrt(sef^2 + sef^2 * varY_hat) = sef * sqrt(1 + varY_hat)
        return sef * sqrt(1.0 + varY_hat)

    def _get_rsquared(self):
        return self._result.rsquared if self._result is not None else 0

    def _get_rsquared_adj(self):
        return self._result.rsquared_adj if self._result is not None else 0

    def _calculate_coefficients(self):
        """
        params = [c,b,a]
        where y=ax**2+bx+c
        """
        return self._result.params if self._result is not None else [0, 0]

    def _calculate_coefficient_errors(self):
        return self._result.bse if self._result is not None else [0, 0]

    def _engine_factory(self, fy, X, check_integrity=True):
        return OLS(fy, X)

    def _get_degree(self):
        return self._degree

    def _set_degree(self, d):
        self.set_degree(d)

    @property
    def summary(self):
        if self._result:
            return self._result.summary()

    @property
    def var_covar(self):
        if self._result:
            return self._result.normalized_cov_params

    def _get_degrees_of_freedom(self):
        return len(self.coefficients)

    def __degree_changed(self):
        if self._degree:
            self.calculate()

    def _get_fit(self):
        return FITS[self._degree - 1]

    def _set_fit(self, v):
        self._set_degree(v)

    def _get_X(self, xs=None):
        """
        Returns the design matrix X = [[1, xi, xi^2, ...], ...].

        Uses np.vander(increasing=True) which is significantly faster than
        building columns via list comprehension + column_stack for higher
        degrees.
        """
        if xs is None:
            xs = self.clean_xs
        return vander(atleast_1d(asarray(xs)), self.degree + 1, increasing=True)


class PolynomialRegressor(OLSRegressor):
    pass


class MultipleLinearRegressor(OLSRegressor):
    """
    xs=[(x1,y1),(x2,y2),...,(xn,yn)]
    ys=[z1,z2,z3,...,zn]

    if you have a list of x's and y's
    X=array(zip(x,y))
    if you have a tuple of x,y pairs
    X=array(xy)
    """

    def fast_predict2(self, endog, pexog, **kw):
        # OLSRegressor fast_predict2 is not working for multiplelinear regressor
        # use fast_predict instead
        return self.fast_predict(endog, pexog, **kw)

    def _get_X(self, xs=None):
        if xs is None:
            xs = self.clean_xs

        xs = asarray(xs)
        x1, x2 = xs.T
        xs = column_stack((x1, x2, ones_like(x1)))
        return xs


# ============= EOF =============================================
