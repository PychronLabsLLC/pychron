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
from numpy import delete, hstack

from statsmodels.api import WLS

from pychron.core.regression.ols_regressor import MultipleLinearRegressor, OLSRegressor


class WeightedPolynomialRegressor(OLSRegressor):
    def _delete_filtered_hook(self, outliers):
        self.yserr = delete(self.yserr, outliers)

    def _engine_factory(self, fy, X, check_integrity=True):
        ws = self._get_weights()
        if not self._check_integrity(fy, X, ws):
            # Single point: duplicate the weight so engine has 2 rows.
            if len(fy) == 2 and len(X) == 2 and len(ws) == 1:
                ws = hstack((ws, ws[0]))
            else:
                return
        return WLS(fy, X, weights=ws)

    def _check_integrity(self, x, y, e=None, **kw):
        nx, ny = len(x), len(y)
        ne = len(e) if e is not None else nx
        if not nx or not ny or not ne:
            return
        if nx != ny or nx != ne:
            return
        if nx == 1 or ny == 1 or ne == 1:
            return
        return True

    def _get_weights(self):
        return self.clean_yserr**-2


class WeightedMultipleLinearRegressor(WeightedPolynomialRegressor, MultipleLinearRegressor):
    pass


# ============= EOF =============================================
