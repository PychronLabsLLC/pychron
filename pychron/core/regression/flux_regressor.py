# ===============================================================================
# Copyright 2013 Jake Ross
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

# ============= standard library imports ========================
from numpy import (
    argsort,
    array,
    asarray,
    average,
    column_stack,
    ones_like,
    ravel,
    searchsorted,
    zeros_like,
)
from scipy.interpolate import Rbf, bisplev, bisplrep, griddata  # type: ignore
from statsmodels.regression.linear_model import OLS, WLS  # type: ignore
from traits.api import Bool, Enum, Int, Str

from pychron.core.geometry.geometry import calc_distances
from pychron.core.regression.base_regressor import BaseRegressor
from pychron.core.regression.ols_regressor import MultipleLinearRegressor
from pychron.core.stats.idw import Invdisttree  # type: ignore
from pychron.pychron_constants import AVERAGE, LINEAR, WEIGHTED_MEAN


class SpecialFluxRegressor(BaseRegressor):
    use_weighted_fit = Bool

    def predict(self, pts):
        return array(self._predict(pts))

    def predict_error(self, pts, error_calc=None):
        return array(self._predict(pts, return_error=True))

    def get_exog(self, x):
        return x

    def _calculate_coefficients(self):
        return ""

    def _calculate_coefficient_errors(self):
        return ""


class InterpolationRegressor(SpecialFluxRegressor):
    def predict(self, pts):
        return self.predict_grid(*pts.T)

    def fast_predict2(self, endog, exog):
        pass

    def predict_grid(self, pts):
        return zeros_like(pts)

    def predict_error(self, pts, **kw):
        return zeros_like(pts)


class BSplineRegressor(InterpolationRegressor):
    def calculate(self):
        x, y = self.clean_xs.T
        self._tck = bisplrep(x, y, self.clean_ys, kx=4, ky=4)

    def predict_grid(self, x, y):
        return bisplev(x, y, self._tck)


class RBFRegressor(InterpolationRegressor):
    rbf_kind = "multiquadric"

    def calculate(self):
        x, y = self.clean_xs.T
        self.rbf = Rbf(x, y, self.clean_ys, function=self.rbf_kind)

    def predict_grid(self, x, y):
        return self.rbf(x, y)

    def fast_predict2(self, endog, exog):
        x, y = exog.T
        fx, fy = self.clean_xs.T
        self.rbf = Rbf(fx, fy, endog, function=self.rbf_kind)
        return self.rbf(x, y)


class GridDataRegressor(InterpolationRegressor):
    method = "cubic"

    def calculate(self):
        pass

    def predict_grid(self, x, y):
        return griddata(self.clean_xs, self.clean_ys, (x, y), method=self.method)

    def fast_predict2(self, endog, exog):
        x, y = exog.T
        return griddata(self.clean_xs, endog, (x, y), method=self.method)


class IDWRegressor(InterpolationRegressor):
    def calculate(self):
        leafsize = 10
        known = self.clean_xs
        z = self.clean_ys
        self._invdisttree = Invdisttree(known, z, leafsize=leafsize, stat=1)

    def predict(self, pts):
        nnear = 8  # 8 2d, 11 3d => 5 % chance one-sided -- Wendel, mathoverflow.com
        eps = 0.1  # approximate nearest, dist <= (1 + eps) * true nearest
        p = 2  # weights ~ 1 / distance**p
        return self._invdisttree(pts, nnear=nnear, eps=eps, p=p)


def lever_fraction(xy, p0, p1):
    """Fraction of ``xy`` projected onto the segment p0->p1 (0 at p0, 1 at p1).

    Uses the scalar projection (dot product) so an unknown that is off the
    p0-p1 line is handled correctly; the previous Euclidean-distance version
    always returned a non-negative magnitude and so could not represent a
    point lying "before" p0. The fraction is left unclamped so points outside
    the pair extrapolate linearly.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d2 = dx * dx + dy * dy
    if d2 == 0:
        return 0.0
    return ((xy[0] - p0[0]) * dx + (xy[1] - p0[1]) * dy) / d2


class NearestNeighborFluxRegressor(SpecialFluxRegressor):
    n = Int(3)
    interpolation_style = Enum(WEIGHTED_MEAN, AVERAGE, LINEAR)

    def set_neighbors(self, unks, mons):
        for unk in unks:
            idx, _ = self._get_neighbors(unk.x, unk.y)
            unk.bracket_a = mons[idx[0]].hole_id
            unk.bracket_b = mons[idx[-1]].hole_id

    def _get_neighbors(self, x, y):
        """Return (sorted indices, distances) for the n nearest points."""
        ds = ravel(calc_distances(self.clean_xs, array([[x, y]])))
        # argsort gives indices of n smallest distances; sort that subset
        # so neighbor order is in index order (preserves bracket semantics).
        nn = argsort(ds)[: self.n]
        nn.sort()
        return nn, ds[nn]

    def _predict(self, pts, return_error=False):
        return [self._predict_one(x, y, return_error) for x, y in pts]

    def _predict_one(self, x, y, return_error):
        idx, _ = self._get_neighbors(x, y)
        if len(idx) == 0:
            return 0

        vs = self.clean_ys[idx]
        style = self.interpolation_style
        if style == WEIGHTED_MEAN:
            ws = self.clean_yserr[idx] ** -2
            if return_error:
                return ws.sum() ** -0.5
            return average(vs, weights=ws)
        if style == AVERAGE:
            return vs.std() if return_error else vs.mean()
        if style == LINEAR:
            p0, p1 = self.clean_xs[idx][0], self.clean_xs[idx][-1]
            f = lever_fraction((x, y), p0, p1)
            if return_error:
                e0, e1 = self.clean_yserr[idx][0], self.clean_yserr[idx][-1]
                # propagate in quadrature, weighted by fractional distance
                return (((1 - f) * e0) ** 2 + (f * e1) ** 2) ** 0.5
            j0, j1 = vs[0], vs[-1]
            return j0 + f * (j1 - j0)
        return 0


class Bracketing1DRegressor(SpecialFluxRegressor):
    """1-D bracketing flux model (lever-rule interpolation).

    Monitors are positioned along a single coordinate (``xs`` is 1-D; the
    caller projects 2-D tray positions onto the chosen axis). For an unknown
    at coordinate ``p`` the straddling monitor pair (one below, one above) is
    located and J is linearly interpolated between them (the lever rule):

        f = (p - x0) / (x1 - x0)
        j = y0 + f * (y1 - y0)

    The error is propagated in quadrature, weighting each monitor by its
    fractional distance::

        jerr = sqrt(((1 - f) * e0)^2 + (f * e1)^2)

    Outside the monitor range the nearest end pair's slope is extrapolated
    (``f`` is allowed outside [0, 1]).
    """

    one_d_axis = Str("X")

    def calculate(self):
        # sort once; order maps sorted index -> original monitor index so
        # set_neighbors can report the bracketing monitors' hole ids.
        self._order = argsort(self.clean_xs)
        self._sxs = self.clean_xs[self._order]
        self._sys = self.clean_ys[self._order]
        self._ses = self.clean_yserr[self._order]

    def _bracket_indices(self, p):
        """Return (lo, hi, f) in sorted-index space for coordinate ``p``.

        lo/hi straddle ``p`` when in range; at/below the low end the first
        pair (0, 1) is used and above the high end the last pair, so ``f``
        extrapolates past the ends.
        """
        sxs = self._sxs
        n = sxs.shape[0]
        hi = int(searchsorted(sxs, p))
        if hi <= 0:
            lo, hi = 0, 1
        elif hi >= n:
            lo, hi = n - 2, n - 1
        else:
            lo = hi - 1

        x0, x1 = sxs[lo], sxs[hi]
        f = 0.0 if x1 == x0 else (p - x0) / (x1 - x0)
        return lo, hi, f

    def _predict_one(self, p, return_error):
        lo, hi, f = self._bracket_indices(p)
        if return_error:
            e0, e1 = self._ses[lo], self._ses[hi]
            return (((1 - f) * e0) ** 2 + (f * e1) ** 2) ** 0.5
        y0, y1 = self._sys[lo], self._sys[hi]
        return y0 + f * (y1 - y0)

    def _predict(self, pts, return_error=False):
        if self._sxs.shape[0] < 2:
            return zeros_like(asarray(pts, dtype=float))
        return [self._predict_one(float(p), return_error) for p in pts]

    def set_neighbors(self, unks, mons):
        if self._sxs.shape[0] < 2:
            return
        order = self._order
        for unk in unks:
            p = unk.x if self.one_d_axis == "X" else unk.y
            lo, hi, _ = self._bracket_indices(float(p))
            unk.bracket_a = mons[order[lo]].hole_id
            unk.bracket_b = mons[order[hi]].hole_id


class BowlFluxRegressor(MultipleLinearRegressor):
    """Quadratic surface: z = a*x1^2 + b*x2^2 + c*x1 + d*x2 + e."""

    def _get_X(self, xs=None):
        if xs is None:
            xs = self.xs
        x1, x2 = asarray(xs).T
        return column_stack((x1**2, x2**2, x1, x2, ones_like(x1)))


class HighOrderPolynominalFluxRegressor(MultipleLinearRegressor):
    """z = sum_i(a_i * x1^i + b_i * x2^i) for i in [1, degree] + intercept."""

    def _get_X(self, xs=None):
        if xs is None:
            xs = self.xs
        x1, x2 = asarray(xs).T
        cols = [xi ** (i + 1) for i in range(self.degree) for xi in (x1, x2)]
        cols.append(ones_like(x1))
        return column_stack(cols)


class PlaneFluxRegressor(MultipleLinearRegressor):
    use_weighted_fit = Bool(False)

    def _get_weights(self):
        e = self.clean_yserr
        if self._check_integrity(e, e):
            return 1 / e**2

    def _engine_factory(self, fy, X, check_integrity=True):
        if self.use_weighted_fit:
            return WLS(fy, X, weights=self._get_weights())
        return OLS(fy, X)


# ============= EOF =============================================
