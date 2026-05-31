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

# ============= standard library imports ========================
from numpy import where

from traits.api import Str

from pychron.core.regression.base_regressor import BaseRegressor


class InterpolationRegressor(BaseRegressor):
    kind = Str

    def _calculate_coefficients(self):
        pass

    def predict(self, xs):
        return self._predict(xs, "value")

    def predict_error(self, xs):
        return self._predict(xs, "error")

    def _predict(self, xs, attr):
        kind = self.kind.replace(" ", "_")
        func = getattr(self, "{}_predictors".format(kind))
        if not hasattr(xs, "__iter__"):
            xs = (xs,)

        exc = self.get_excluded()
        # Drop None values from failed integrity checks.
        return [v for v in (func(xi, exc, attr) for xi in xs) if v is not None]

    def succeeding_predictors(self, *args, **kw):
        return self._adjacent_predictors("after", *args, **kw)

    def preceding_predictors(self, *args, **kw):
        return self._adjacent_predictors("before", *args, **kw)

    def _adjacent_predictors(self, direction, timestamp, exc, attr="value"):
        xs, ys, es = self.xs, self.ys, self.yserr
        if not self._check_integrity(xs, ys) or not self._check_integrity(ys, es):
            return

        if direction == "before":
            hits = where(xs <= timestamp)[0]
            ti = hits[-1] if len(hits) else 0
            while ti in exc and ti > 0:
                ti -= 1
        else:
            n = len(xs)
            hits = where(xs >= timestamp)[0]
            ti = hits[0] if len(hits) else n - 1
            while ti in exc and ti < n:
                ti += 1

        source = ys if attr == "value" else es
        return source[ti]

    def bracketing_average_predictors(self, tm, exc, attr="value"):
        try:
            pb, ab, _, _ = self._bracketing_predictors(tm, exc, attr)
        except TypeError:
            return (self.ys if attr == "value" else self.yserr)[0]

        if attr == "value":
            return (pb + ab) / 2.0
        return ((pb**2 + ab**2) ** 0.5) / 2.0

    def bracketing_interpolate_predictors(self, tm, exc, attr="value"):
        try:
            pb, ab, x, _ = self._bracketing_predictors(tm, exc, attr)
        except TypeError:
            return (self.ys if attr == "value" else self.yserr)[0]

        source = self.yserr if attr == "error" else self.ys
        if tm >= x[1]:
            return source[-1]
        if tm <= x[0]:
            return source[0]

        f = (tm - x[0]) / (x[1] - x[0])
        if attr == "error":
            # Geometrically sum the errors weighted by the fractional distance.
            return (((1 - f) * pb) ** 2 + (f * ab) ** 2) ** 0.5
        return pb + f * (ab - pb)

    def _bracketing_predictors(self, tm, exc, attr):
        xs, ys, es = self.xs, self.ys, self.yserr
        n = self.n
        hits = where(xs < tm)[0]
        if len(hits):
            ti = hits[-1]
            li = ti
            hi = min(ti + 1, n - 1)
            while li in exc and li > 0:
                li -= 1
            while hi in exc and hi < n - 1:
                hi += 1
        else:
            li = hi = 0

        source = ys if attr == "value" else es
        return source[li], source[hi], (xs[li], xs[hi]), (li, hi)


# ============= EOF =============================================
