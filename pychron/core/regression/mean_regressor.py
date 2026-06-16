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
# ============= standard library imports ========================

from numpy import average, full, isscalar, where

from pychron.core.helpers.formatting import floatfmt
from pychron.pychron_constants import MSEM, SE, SEM
from .base_regressor import BaseRegressor


def _length(x):
    if isinstance(x, (list, tuple)):
        return len(x)
    return x.shape[0]


class MeanRegressor(BaseRegressor):
    _fit = "average"  # type: ignore[assignment]

    def get_exog(self, pts):
        return pts

    def fast_predict2(self, endog, exog):
        return full(exog.shape[0], endog.mean())

    def calculate(self, filtering=False, **kw):
        if not filtering:
            # prevent infinite recursion
            self.calculate_filtered_data()
        self.clear_dirty()

    def calculate_outliers(self):
        nsigma = self.filter_outliers_dict.get("std_devs", 2)
        bound = self.std * nsigma
        self.filter_bound_value = bound
        residuals = abs(self.ys - self.mean)
        return where(residuals >= bound)[0]

    def _calculate_coefficients(self):
        ys = self.clean_ys
        if self._check_integrity(ys, ys):
            return [ys.mean()]
        return [0]

    def _calculate_coefficient_errors(self):
        return [self.std, self.sem]

    @property
    def summary(self):
        return "mean={}\nstd={}\nsem={}\n\n".format(self.mean, self.std, self.sem)

    def predict(self, xs=None, *args):
        m = self.mean
        if xs is None or isscalar(xs):
            return m
        return full(_length(xs), m)

    def calculate_ci(self, fx, fy):
        e = self.predict_error(fx)
        return fy - e, fy + e

    def tostring(self, sig_figs=3):
        m = self.mean
        std = self.std
        sem = self.sem
        se = self.se

        sm = floatfmt(m, n=9)
        sstd = floatfmt(std, n=9)
        ssem = floatfmt(sem, n=9)
        sse = floatfmt(se, n=9)

        pstd = self.format_percent_error(m, std)
        psem = self.format_percent_error(m, sem)
        pse = self.format_percent_error(m, se)

        n = self.n
        tn = self.xs.shape[0]
        s = "mean={}, n={}({}), std={} ({}), sem={} ({}) se={} ({})".format(
            sm, n, tn, sstd, pstd, ssem, psem, sse, pse
        )
        # s = fmt.format(m, std, self.percent_error(m, std),
        #                sem, self.percent_error(m, sem))
        return s

    def make_equation(self):
        return "Mean"

    def predict_error(self, x, error_calc=None):
        """
        Error term for a mean-style fit. Resolution of `error_calc`:

          SEM  → standard error of the mean. Subclasses define `sem`:
                 base = std/√n;  WeightedMean = Taylor (1/√Σw).
          MSEM → SEM × √MSWD (when MSWD>1) — standard ISOPLOT scaling.
                 Uses `self.sem` so that base and weighted regressors apply
                 √MSWD to the *same kind* of standard error (the SEM of the
                 mean), not to mixed quantities.
          SE   → `self.se`. For base mean: equal to `std` (preserved for
                 backward compatibility with mass-spec output conventions).
                 For weighted mean: equal to Taylor SEM.
          SD   → sample standard deviation.
        """
        if error_calc is None:
            error_calc = self.error_calc_type or ("SEM" if "sem" in self.fit.lower() else "SD")

        ec = error_calc.lower()
        if ec == SEM.lower():
            e = self.sem
        elif ec in (MSEM.lower(), "msem"):
            e = self.sem * self._mswd_scale()
        elif ec == SE.lower():
            e = self.se
        else:
            e = self.std

        if isscalar(x):
            return e
        return full(_length(x), e)

    def calculate_standard_error_fit(self):
        return self.std

    def _check_integrity(self, x, y):
        if x is None or y is None:
            return
        nx, ny = x.shape[0], y.shape[0]
        if not nx or not ny or nx != ny:
            return
        return True


class WeightedMeanRegressor(MeanRegressor):
    def fast_predict2(self, endog, exog):
        ws = self._get_weights()
        return full(exog.shape[0], average(endog, weights=ws))

    @property
    def se(self):
        """Taylor error / standard error of the weighted mean."""
        return self.sem

    @property
    def sem(self):
        """
        Weighted SEM = Taylor error = 1/√Σw, where w_i = 1/σ_i².
        Overrides base class `std/√n` which would be the unweighted SEM.
        """
        ws = self._get_weights()
        if ws is None:
            return 0
        return ws.sum() ** -0.5

    @property
    def mean(self):
        ys = self.clean_ys
        ws = self._get_weights()
        if ws is not None and self._check_integrity(ys, ws):
            return average(ys, weights=ws)
        return average(ys)

    def _get_weights(self):
        e = self.clean_yserr
        if self._check_integrity(e, e):
            return e**-2


# ============= EOF =============================================
