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
from numpy import inf as Inf, zeros_like
from scipy.optimize import fsolve
from traits.api import Array, Float, Property
from uncertainties import correlated_values, std_dev, ufloat

from pychron.core.helpers.logger_setup import new_logger
from pychron.core.regression.ols_regressor import OLSRegressor
from pychron.core.stats import calculate_mswd2
from pychron.core.stats.core import validate_mswd
from pychron.pychron_constants import MSE, SE

logger = new_logger("YorkRegressor")


class YorkRegressor(OLSRegressor):
    """York 1969, Mahon 1996"""

    xns = Array
    xds = Array

    yns = Array
    yds = Array

    xnes = Array
    xdes = Array

    ynes = Array
    ydes = Array

    slope = Property
    _slope = Float

    intercept = Property
    _intercept = Float
    _intercept_variance = None

    x_intercept = Property
    x_intercept_error = Property

    mswd = Property
    error_calc_type = SE

    def calculate(self, *args, **kw):
        super(YorkRegressor, self).calculate(*args, **kw)
        if not len(self.xserr) or not len(self.yserr):
            return
        self._calculate()

    def calculate_correlation_coefficients(self, clean=True):
        if not len(self.xds):
            return zeros_like(self.clean_xs)

        arrays = [self.xds, self.xns, self.xdes, self.xnes, self.yns, self.ynes]
        if clean:
            arrays = [self._clean_array(a) for a in arrays]
        xds, xns, xdes, xnes, yns, ynes = arrays

        fd = xdes / xds  # f40Ar
        fyn = ynes / yns  # f36Ar
        fxn = xnes / xns  # f39Ar
        return ((1 + (fyn / fd) ** 2) * (1 + (fxn / fd) ** 2)) ** -0.5

    def _get_weights(self):
        ex = self.clean_xserr
        ey = self.clean_yserr
        Wx = ex**-2
        Wy = ey**-2
        return Wx, Wy

    def _calculate_UV(self, W):
        xs = self.clean_xs
        ys = self.clean_ys

        # xs, ys = self.xs, self.ys
        x_bar, y_bar = self._calculate_xy_bar(W)
        U = xs - x_bar
        V = ys - y_bar
        return U, V

    def _calculate_xy_bar(self, W):
        # xs, ys = self.xs, self.ys
        xs, ys = self.clean_xs, self.clean_ys
        sW = sum(W)
        try:
            x_bar = sum(W * xs) / sW
            y_bar = sum(W * ys) / sW
        except ZeroDivisionError:
            x_bar, y_bar = 0, 0

        return x_bar, y_bar

    def get_slope(self):
        self.calculate()
        return self._slope

    def get_intercept(self):
        self.calculate()
        return self._intercept

    def get_intercept_error(self):
        if self.error_calc_type == "CI":
            e = self.calculate_ci_error(0)[0]
        # elif self.error_calc_type in (SEM, MSEM):
        #     e = (self.get_intercept_variance() ** 0.5) * self.n ** -0.5
        elif self.error_calc_type in (SE, MSE):
            e = self.get_intercept_variance() ** 0.5
        else:
            e = 0

        return e

    def get_intercept_variance(self):
        if self._intercept_variance is None:
            self.get_slope_variance()

        return self._intercept_variance

    def get_slope_variance(self):
        b = self._slope
        W = self._calculate_W(b)
        U, V = self._calculate_UV(W)

        sigbsq = 1 / sum(W * U**2)

        sigasq = sigbsq * sum(W * self.clean_xs**2) / sum(W)

        self._intercept_variance = sigasq
        return sigbsq

    def get_slope_error(self):
        return self.get_slope_variance() ** 0.5

    def get_x_intercept(self):
        """
        x_intercept = -a/b with full variance propagation.

        Uses York identity a = ybar(W) - b*xbar(W) → cov(a, b) = -xbar(W)*var(b).
        Subclasses override `_get_solution_W()` to handle their own weighting.
        """
        b = self._slope
        a = self._intercept
        if not b:
            return ufloat(0, 0)

        var_b = self.get_slope_variance()
        var_a = self.get_intercept_variance()
        xbar = self._get_xbar_for_covariance()
        cov_ab = -xbar * var_b

        a_u, b_u = correlated_values([a, b], [[var_a, cov_ab], [cov_ab, var_b]])
        return -a_u / b_u

    def _get_xbar_for_covariance(self):
        """Subclass hook: weighted x mean used by the fit."""
        W = self._calculate_W(self._slope)
        xbar, _ = self._calculate_xy_bar(W)
        return xbar

    def _get_slope(self):
        return self._slope

    def _get_intercept(self):
        return self._intercept

    def _get_x_intercept(self):
        return -self.intercept / self.slope

    def _get_mswd(self):
        if not self._slope:
            self.calculate()
        a = self.intercept
        b = self.slope
        x, y, sx, sy = self.clean_xs, self.clean_ys, self.clean_xserr, self.clean_yserr

        v = 0
        if len(sx) and len(sy):
            v = calculate_mswd2(
                x, y, sx, sy, a, b, corrcoeffs=self.calculate_correlation_coefficients()
            )
            self.valid_mswd = validate_mswd(v, len(x), k=2)

        return v

    def _calculate_W(self, b):
        sig_x = self.clean_xserr
        sig_y = self.clean_yserr

        var_x = sig_x**2
        var_y = sig_y**2
        r = self.calculate_correlation_coefficients()
        # print var_x.shape, var_y.shape, r.shape, b
        return (var_y + b**2 * var_x - 2 * b * r * sig_x * sig_y) ** -1

    def _calculate(self, total=500, tol=1e-10):
        """
        Iteratively solve for slope b. Each iteration recomputes the
        York weights W(b) and yields a new estimate nb. Converges when
        |b - prev_b| < tol.
        """
        sig_x = self.clean_xserr
        sig_y = self.clean_yserr
        var_x = sig_x**2
        var_y = sig_y**2
        r = self.calculate_correlation_coefficients()
        sxy = r * sig_x * sig_y

        b = 0.0
        prev = Inf
        cnt = 0
        while abs(prev - b) >= tol and cnt < total:
            W = self._calculate_W(b)
            U, V = self._calculate_UV(W)
            common = U * var_y + b * V * var_x
            sumA = (W**2 * V * (common - V * sxy)).sum()
            sumB = (W**2 * U * (common - b * U * sxy)).sum()
            if sumB == 0:
                break
            prev = b
            b = sumA / sumB
            cnt += 1

        if cnt >= total:
            logger.warning("York regression did not converge")

        W = self._calculate_W(b)
        xbar, ybar = self._calculate_xy_bar(W)
        self._slope = b
        self._intercept = ybar - b * xbar

    def predict(self, x):
        m, b = self._slope, self._intercept
        return m * x + b


class NewYorkRegressor(YorkRegressor):
    """
    Mahon (1996) error propagation.
    Adapted from https://github.com/LLNL/MahonFitting/blob/master/mahon.py
    (Trappitsch et al. 2018).
    """

    def get_slope_variance(self):
        b = self._slope
        W = self._calculate_W(b)
        U, V = self._calculate_UV(W)

        var_x = self.clean_xserr**2
        var_y = self.clean_yserr**2
        sxy = self.calculate_correlation_coefficients() * self.clean_xserr * self.clean_yserr

        # eq 19: d(theta)/db
        aa = 2 * b * (U * V * var_x - U**2 * sxy)
        bb = U**2 * var_y - V**2 * var_x
        cc = W**3 * (sxy - b * var_x)
        dd = (
            b**2 * (U * V * var_x - U**2 * sxy)
            + b * (U**2 * var_y - V**2 * var_x)
            - (U * V * var_y - V**2 * sxy)
        )
        dthdb = (W**2 * (aa + bb)).sum() + 4 * (cc * dd).sum()

        xbar, _ = self._calculate_xy_bar(W)
        wksum = W.sum()
        ww = W / wksum  # per-point fractional weight

        # x[j], xx[j]: terms for d(theta)/dxi and d(theta)/dyi
        x = b**2 * (V * var_x - 2 * U * sxy) + 2 * b * U * var_y - V * var_y
        xx = b**2 * U * var_x + 2 * V * sxy - 2 * b * V * var_x - U * var_y

        # Vectorize the original O(n^2) loop. For each i:
        #   dthdxi[i] = sum_j(wj^2 * (delta_ij - ww[i]) * x[j])
        #             = wi^2 * x[i] - ww[i] * sum_j(wj^2 * x[j])
        Sx = (W**2 * x).sum()
        Sxx = (W**2 * xx).sum()
        dthdx = W**2 * x - ww * Sx
        dthdy = W**2 * xx - ww * Sxx

        # d(intercept)/dxi, d(intercept)/dyi
        dadx = -b * ww - xbar * dthdx / dthdb
        dady = ww - xbar * dthdy / dthdb

        sigbsq = (dthdx**2 * var_x + dthdy**2 * var_y + 2 * sxy * dthdx * dthdy).sum() / dthdb**2
        sigasq = (dadx**2 * var_x + dady**2 * var_y + 2 * sxy * dadx * dady).sum()

        self._intercept_variance = sigasq
        return sigbsq


class ReedYorkRegressor(YorkRegressor):
    """
    reed 1989
    """

    _degree = 1

    #     def _set_degree(self, d):
    #         '''
    #             York regressor only for linear fit
    #         '''
    #         self._degree = 2
    def _get_weights(self):
        wx = self.clean_xserr**-2
        wy = self.clean_yserr**-2

        return wx, wy

    def _calculate(self):
        if self.coefficients is None:
            return

        Wx, Wy = self._get_weights()

        def f(mi):
            W = self._calculate_W(mi, Wx, Wy)
            U, V = self._calculate_UV(W)

            suma = sum((W**2 * U * V) / Wx)
            S = sum((W**2 * U**2) / Wx)

            a = (2 * suma) / (3 * S)

            sumB = sum((W**2 * V**2) / Wx)
            B = (sumB - sum(W * U**2)) / (3 * S)

            g = -sum(W * U * V) / S

            ff = pow(mi, 3) - 3 * a * pow(mi, 2) + 3 * B * mi - g
            return ff

        m = self.coefficients[-1]
        roots = fsolve(f, (m,))
        slope = roots[0]

        self._slope = slope

        W = self._calculate_W(slope, Wx, Wy)
        x_bar, y_bar = self._calculate_xy_bar(W)
        self._intercept = y_bar - slope * x_bar

    def _calculate_W(self, slope, Wx, Wy):
        W = Wx * Wy / (slope**2 * Wy + Wx)
        return W

    def _get_xbar_for_covariance(self):
        Wx, Wy = self._get_weights()
        W = self._calculate_W(self._slope, Wx, Wy)
        xbar, _ = self._calculate_xy_bar(W)
        return xbar

    def get_intercept_variance(self):
        var_slope = self.get_slope_variance()
        wx, wy = self._get_weights()
        w = self._calculate_W(self._slope, wx, wy)
        return var_slope * (w * self.clean_xs**2).sum() / w.sum()

    def get_slope_variance(self):
        """
        Reed (1992) eq 14: MSWD-scaled slope variance.

            σ_b² = Σ(W·(bU - V)²) / ((n-2) · Σ(W·U²))
                 = MSWD · (1 / Σ(W·U²))

        Equivalent to the York 1969 basic form `1/Σ(W·U²)` multiplied by
        the reduced chi-squared (MSWD). For perfect fit (MSWD=1) the two
        forms coincide; otherwise Reed's form inflates the error to
        account for excess scatter.
        """
        n = len(self.clean_xs)
        Wx, Wy = self._get_weights()
        slope = self._slope
        W = self._calculate_W(slope, Wx, Wy)
        U, V = self._calculate_UV(W)

        sumB = (W * U**2).sum()
        if n <= 2 or sumB == 0:
            return 0
        sumA = (W * (slope * U - V) ** 2).sum()
        return sumA / (sumB * (n - 2))

    def predict(self, x, *args, **kw):
        return self.get_slope() * x + self.get_intercept()


# ============= EOF =============================================
