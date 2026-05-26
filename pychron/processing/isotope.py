# ===============================================================================
# Copyright 2012 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================

# ============= enthought library imports =======================
# from traits.api import HasTraits, Str, Float, Property, Instance, \
#     String, Either, Dict, cached_property, Event, List, Bool, Int, Array
# ============= standard library imports ========================
import re
import struct
from binascii import hexlify
from math import isnan, isinf

import six
from numpy import array, inf, polyfit, gradient, array_split, mean, isfinite
from uncertainties import ufloat, nominal_value, std_dev

from pychron.core.geometry.geometry import curvature_at
from pychron.core.helpers.binpack import unpack
from pychron.core.helpers.fits import natural_name_fit, fit_to_degree
from pychron.core.helpers.logger_setup import new_logger
from pychron.core.regression.least_squares_regressor import (
    ExponentialRegressor,
    FitError,
    LeastSquaresRegressor,
)
from pychron.core.regression.mean_regressor import MeanRegressor
from pychron.core.regression.ols_regressor import PolynomialRegressor
from pychron.pychron_constants import AUTO_N

logger = new_logger("Isotope")


def fit_abbreviation(
    fit,
):
    f = ""
    if fit:
        f = fit[0].upper()
    return f


class BaseMeasurement(object):
    unpack_error = None
    endianness = ">"
    reverse_unpack = False
    use_manual_value = False
    use_manual_error = False
    units = "fA"
    _n = None
    detector = None
    detector_serial_id = None
    group_data = 0
    _regressor = None

    @property
    def n(self):
        if self._n:
            return self._n

        return self.xs.shape[0]

    @n.setter
    def n(self, v):
        self._n = v

    @property
    def offset_xs(self):
        return self.xs - self.time_zero_offset

    def __init__(self, name, detector):
        self.name = name
        self.detector = detector
        self.xs, self.ys = array([]), array([])
        self.mass = 0
        self.time_zero_offset = 0
        self._regression_state = None

    def set_grouping(self, n):
        if self.group_data == n:
            return
        self.group_data = n
        self._invalidate_regressor()
        # if self._regressor:
        #     self._regressor.dirty = True

    def get_data(self):
        xs = self.offset_xs
        ys = self.ys
        if self.group_data > 1:
            n = len(xs) // self.group_data
            xs = [mean(g) for g in array_split(xs, n)]
            ys = [mean(g) for g in array_split(ys, n)]

        return xs, ys

    def pack(self, endianness=None, as_hex=True):
        if endianness is None:
            endianness = self.endianness

        fmt = "{}ff".format(endianness)
        txt = b"".join((struct.pack(fmt, x, y) for x, y in zip(self.xs, self.ys)))
        if as_hex:
            txt = hexlify(txt)
        return txt

    def unpack_data(self, blob, n_only=False):
        if not blob:
            return

        try:
            xs, ys = self._unpack_blob(blob)
        except (ValueError, TypeError, IndexError, AttributeError) as e:
            self.unpack_error = e
            return

        if n_only:
            self.n = len(xs)
        else:
            self.xs = array(xs)
            self.ys = array(ys)

            # print self.name, self.xs.shape, self.ys.shape
            # print self.name, self.ys

    def _unpack_blob(self, blob, endianness=None):
        if endianness is None:
            endianness = self.endianness

        try:
            x, y = unpack(blob, fmt="{}ff".format(endianness))
            # x, y = zip(*[struct.unpack('{}ff'.format(endianness), blob[i:i + 8]) for i in range(0, len(blob), 8)])
            if self.reverse_unpack:
                return y, x
            else:
                return x, y

        except struct.error as e:
            logger.warning("Unpack blob failed for %s: %s", self.name, e)

    def get_slope(self, n=-1):
        if self.xs.shape[0] and self.ys.shape[0] and self.xs.shape[0] == self.ys.shape[0]:
            xs = self.offset_xs
            ys = self.ys
            if n != -1:
                xs = xs[-n:]
                ys = ys[-n:]

            xs = xs[isfinite(xs)]
            ys = ys[isfinite(ys)]
            try:
                return polyfit(xs, ys, 1)[0]
            except Exception as e:
                logger.debug("Get slope failed for %s: %s", self.name, e)
                return 0
        else:
            return 0

    def get_curvature(self, x):
        ys = self._get_curvature_ys()
        if ys is not None and len(ys):
            # if x is between 0-1 treat as a percentage of the total number of points
            if 0 < x < 1:
                x = self.xs.shape[0] * x

            return curvature_at(ys, x)
        else:
            return 0

    def _get_curvature_ys(self):
        return self.ys


class IsotopicMeasurement(BaseMeasurement):
    fit_blocks = None
    error_type = None
    filter_outliers_dict = None
    include_baseline_error = False
    use_static = False
    user_defined_value = False
    user_defined_error = False
    use_stored_value = False
    reviewed = False
    ic_factor_reviewed = False
    ic_factor_fit = None

    _value = 0
    _error = 0
    truncate = None
    _fit = None

    _oerror = None
    _ovalue = None

    _fn = None

    # Cached intercept-at-t=0: a single ufloat shared by `value`, `error`,
    # and `uvalue` accessors. Built once per regression-state; invalidated
    # by `_invalidate_regressor` and refreshed inside `_regressor_factory`.
    # Sharing a single ufloat keeps the correlation graph consistent —
    # multiple accesses no longer create independent random variables.
    _cached_uvalue = None
    # Compact token used to detect data swaps that bypass setters
    # (e.g. `iso.ys = new_array` direct assignment). Uses id() of xs/ys
    # arrays plus the regression parameters that influence predict(0).
    _cache_token = None

    def __init__(self, *args, **kw):
        super(IsotopicMeasurement, self).__init__(*args, **kw)
        self.filter_outliers_dict = dict()

    def get_linear_rsquared(self):
        from pychron.core.regression.ols_regressor import OLSRegressor

        reg = OLSRegressor(fit="linear", xs=self.offset_xs, ys=self.ys)
        reg.calculate()
        return reg.rsquared

    def get_rsquared(self):
        return self._regressor.rsquared

    def get_gradient(self):
        return ((gradient(self.ys) ** 2).sum()) ** 0.5

    @property
    def efit(self):
        fit = self.fit
        if fit and "_" not in fit:
            fit = "{}_{}".format(fit, self.error_type)
        return fit

    @property
    def rsquared(self):
        if self._regressor:
            return self._regressor.rsquared

    @property
    def rsquared_adj(self):
        if self._regressor:
            return self._regressor.rsquared_adj

    @property
    def fn(self):
        if self._fn is not None:
            n = self._fn
        elif self._regressor:
            n = self._regressor.clean_xs.shape[0]
        else:
            n = self.n

        return n

    @fn.setter
    def fn(self, v):
        self._fn = v

    @property
    def user_excluded(self):
        if self._regressor:
            return [int(i) for i in self._regressor.user_excluded]

    @property
    def outlier_excluded(self):
        if self._regressor:
            return [int(i) for i in self._regressor.outlier_excluded]

    def set_user_excluded(self, ue):
        if ue:
            reg = self._regressor
            if not reg:
                reg = self.regressor

            reg.ouser_excluded = ue

    def set_filtering(self, d):
        d = d.copy()
        if self.filter_outliers_dict == d:
            return

        self.filter_outliers_dict = d
        if self._regressor:
            self._regressor.dirty = True

    def set_fit_blocks(self, fit):
        """
        fit: either tuple of (fit, error_type) or str
        if str either linear, parabolic etc or
        a fit block e.g
            1.  (,10,average)
                fit average from start to 10 counts
            2.  (10,,linear)
                fit linear from 10 to end counds
        """
        if isinstance(fit, tuple):
            fit, error = fit
            self.error_type = error

        if re.match(r"\([\w\d\s,]*\)", fit):
            fs = []
            for m in re.finditer(r"\([\w\d\s,]*\)", fit):
                a = m.group(0)
                a = a[1:-1]
                s, e, f = (ai.strip() for ai in a.split(","))
                if s == "":
                    s = -1
                else:
                    s = int(s)

                if e == "":
                    e = inf
                else:
                    e = int(e)

                fs.append((s, e, f))

            self.fit_blocks = fs
        else:
            self.fit = fit

    def get_fit(self, cnt):
        r = self.get_fit_block(cnt)
        if r is not None:
            self.fit = r

        return self.fit

    def get_fit_block(self, cnt):
        if self.fit_blocks:
            if cnt < 0:
                return self.fit_blocks[-1][2]
            else:
                for s, e, f in self.fit_blocks:
                    if s < cnt < e:
                        return f

    def set_filter_outliers_dict(
        self,
        filter_outliers=True,
        iterations=1,
        std_devs=2,
        use_standard_deviation_filtering=False,
        use_iqr_filtering=False,
    ):
        self.filter_outliers_dict = {
            "filter_outliers": filter_outliers,
            "iterations": iterations,
            "std_devs": std_devs,
            "use_standard_deviation_filtering": use_standard_deviation_filtering,
            "use_iqr_filtering": use_iqr_filtering,
        }

        self._fn = None
        if self._regressor:
            self._regressor.dirty = True

    def attr_set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def set_fit_error_type(self, e):
        self.attr_set(error_type=e)

    def set_fit(self, fit, notify=True):
        if fit is not None:
            self.user_defined_value = False
            self.user_defined_error = False

            if isinstance(fit, (int, str, six.text_type)):
                self.attr_set(fit=fit)
            elif isinstance(fit, dict):
                self.attr_set(**fit)
            else:
                fitname = fit.fit
                if fitname == AUTO_N:
                    fitname = fit.auto_fit(self.n)
                elif fitname == "Custom":
                    fitname = "custom:{}".format(fit.fitfunc)

                self.attr_set(
                    fit=fitname,
                    time_zero_offset=fit.time_zero_offset or self.time_zero_offset,
                    error_type=fit.error_type or "SEM",
                    include_baseline_error=fit.include_baseline_error or False,
                )

                self.set_filter_outliers_dict(
                    filter_outliers=bool(fit.filter_outliers),
                    iterations=int(fit.filter_outlier_iterations or 0),
                    std_devs=int(fit.filter_outlier_std_devs or 0),
                    use_standard_deviation_filtering=fit.use_standard_deviation_filtering,
                    use_iqr_filtering=fit.use_iqr_filtering,
                )
                self.truncate = fit.truncate

            self._invalidate_regressor()

    def set_uvalue(self, v):
        if isinstance(v, tuple):
            self._value, self._error = v
        else:
            self._value, self._error = nominal_value(v), std_dev(v)
        self._cached_uvalue = None
        self._cache_token = None

    def _revert_user_defined(self):
        self.user_defined_error = False
        self.user_defined_value = False
        if self._ovalue is not None:
            self._value = self._ovalue
        if self._oerror is not None:
            self._error = self._oerror
        self._cached_uvalue = None

    def _current_cache_token(self):
        """
        Cheap signature of the inputs that determine `predict(0)`.

        Uses `id()` of xs/ys so a wholesale array swap (`iso.ys = new`)
        invalidates the cache without us having to hash the contents.
        In-place mutation (`iso.ys[0] = X`) is NOT caught — callers must
        invalidate explicitly in that case (already true for the old code
        path before any caching existed).
        """
        fod = self.filter_outliers_dict
        return (
            id(self.xs),
            id(self.ys),
            self._fit,
            self.error_type,
            self.truncate,
            self.time_zero_offset,
            self.group_data,
            tuple(sorted(fod.items())) if fod else (),
        )

    def _predict_at_t_zero(self):
        """
        Single regressor pass that returns (value, error) at t=0.

        Cached as `_cached_uvalue` so that repeated `value`, `error`, and
        `uvalue` accesses share the SAME ufloat instance (preserves the
        uncertainties correlation graph) and skip redundant regressor work.
        Fast path: tuple-compare against `_cache_token`. Slow path: rebuild
        the regressor and refresh both the cache and the token.
        """
        token = self._current_cache_token()
        if self._cached_uvalue is not None and self._cache_token == token:
            uv = self._cached_uvalue
            return nominal_value(uv), std_dev(uv)

        reg = self.regressor
        v = reg.predict(0)
        e = reg.predict_error(0)
        if isnan(v) or isinf(v):
            v = 0
        if isnan(e) or isinf(e):
            e = 0
        self._cached_uvalue = ufloat(v, e, tag=self.name)
        self._cache_token = token
        return v, e

    @property
    def value(self):
        if not self.use_stored_value and not self.user_defined_value and self.xs.shape[0] > 1:
            return self._predict_at_t_zero()[0]
        return self._value

    @property
    def error(self):
        if not self.use_stored_value and not self.user_defined_error and self.xs.shape[0] > 1:
            return self._predict_at_t_zero()[1]
        return self._error

    @error.setter
    def error(self, v):
        self.user_defined_error = True
        try:
            self._error = float(v)
            self._cached_uvalue = None
        except ValueError:
            pass

    @value.setter
    def value(self, v):
        self.user_defined_value = True
        try:
            self._value = float(v)
            self._cached_uvalue = None
        except ValueError:
            pass

    @property
    def regressor(self):
        fit = self.fit
        if fit is None:
            fit = "linear"
            self.fit = fit
        return self._regressor_factory(fit)

    def _regressor_factory(self, fit):
        lfit = fit.lower()
        reg = self._regressor

        # Fast short-circuit: if an existing regressor was built for the
        # exact same inputs (xs/ys identity + params), return it without
        # touching set_regression_state / determine_fit / calculate.
        if reg is not None and self._regression_state is not None:
            current_token = self._current_cache_token()
            if self._cache_token == current_token:
                return reg

        if "average" in lfit:
            if not isinstance(reg, MeanRegressor):
                reg = MeanRegressor()
        elif lfit == "exponential":
            if not isinstance(reg, ExponentialRegressor):
                reg = ExponentialRegressor()
        elif lfit.startswith("custom:"):
            if not isinstance(reg, LeastSquaresRegressor):
                reg = LeastSquaresRegressor()
                reg.construct_fitfunc(lfit)
        elif not isinstance(reg, PolynomialRegressor):
            reg = PolynomialRegressor()
            reg.set_degree(fit, refresh=False)

        xs, ys = self.get_data()
        state_changed = reg.set_regression_state(
            xs=xs,
            ys=ys,
            filter_outliers_dict=self.filter_outliers_dict,
            truncate=self.truncate,
        )
        reg.trait_setq(error_calc_type=self.error_type or "SEM", tag=self.name)

        if self.truncate:
            reg.set_truncate(self.truncate)
        try:
            fit = reg.determine_fit(lfit)
            self.fit = fit
            recompute = state_changed or reg.is_dirty or getattr(reg, "_result", None) is None
            if recompute:
                reg.calculate()
                # Predicted value at t=0 may change; drop the ufloat cache.
                self._cached_uvalue = None
                self._cache_token = None
        except FitError:
            reg = self._regressor_factory("average")

        self._regressor = reg
        self._regression_state = self._make_regression_state(xs, ys)
        return reg

    def _invalidate_regressor(self):
        self._regressor = None
        self._regression_state = None
        self._cached_uvalue = None
        self._cache_token = None

    def _make_regression_state(self, xs, ys):
        return (
            tuple(xs.tolist()) if hasattr(xs, "tolist") else tuple(xs),
            tuple(ys.tolist()) if hasattr(ys, "tolist") else tuple(ys),
            self.fit,
            self.error_type or "SEM",
            tuple(sorted(self.filter_outliers_dict.items())),
            self.truncate,
            self.group_data,
            self.time_zero_offset,
        )

    @property
    def uvalue(self):
        """
        Return the cached ufloat at t=0. Multiple accesses return the
        SAME ufloat instance, so chained calculations preserve their
        correlation graph (previously each access created an independent
        random variable, double-counting analytical uncertainty).
        """
        if (
            not self.use_stored_value
            and not self.user_defined_value
            and not self.user_defined_error
            and self.xs.shape[0] > 1
        ):
            self._predict_at_t_zero()
            uv = self._cached_uvalue
            if uv is not None:
                return uv
        return ufloat(self.value, self.error, tag=self.name)

    @property
    def fit_abbreviation(self):
        return "{}{}".format(
            fit_abbreviation(self.fit),
            "*" if self.filter_outliers_dict.get("filter_outliers") else "",
        )

    # def _get_fit_abbreviation(self):
    #     return '{}{}'.format(fit_abbreviation(self.fit),
    #                          '*' if self.filter_outliers_dict.get('filter_outliers') else '')

    @property
    def fit(self):
        return self._fit

    @fit.setter
    def fit(self, f):
        f = natural_name_fit(f)
        self._fit = f

    def standard_fit_error(self):
        return self.regressor.calculate_standard_error_fit()

    def noutliers(self):
        return self.regressor.xs.shape[0] - self.regressor.clean_xs.shape[0]

    def _get_curvature_ys(self):
        return self.regressor.predict(self.offset_xs)

    # def _error_type_changed(self):
    #     self.regressor.error_calc_type = self.error_type

    # ===============================================================================
    # arithmetic
    # ===============================================================================
    def __add__(self, a):
        return self.uvalue + a

    def __radd__(self, a):
        return self.__add__(a)

    def __mul__(self, a):
        return self.uvalue * a

    def __rmul__(self, a):
        return self.__mul__(a)

    def __sub__(self, a):
        return self.uvalue - a

    def __rsub__(self, a):
        return a - self.uvalue

    def __div__(self, a):
        return self.uvalue / a

    def __rdiv__(self, a):
        return a / self.uvalue


class CorrectionIsotopicMeasurement(IsotopicMeasurement):
    pass
    # def __init__(self, dbrecord=None, *args, **kw):
    #     if dbrecord:
    #         self._value = dbrecord.user_value if dbrecord.user_value is not None else 0
    #         self._error = dbrecord.user_error if dbrecord.user_value is not None else 0
    #
    #     super(IsotopicMeasurement, self).__init__(*args, **kw)


class Background(CorrectionIsotopicMeasurement):
    pass


class Baseline(IsotopicMeasurement):
    _kind = "baseline"


class Sniff(BaseMeasurement):
    pass


class Whiff(BaseMeasurement):
    pass


class BaseIsotope(IsotopicMeasurement):
    baseline = None

    # baseline_fit_abbreviation = Property(depends_on='baseline:fit')

    def set_grouping(self, n):
        super(BaseIsotope, self).set_grouping(n)
        self.baseline.set_grouping(n)

    @property
    def intercept_percent_error(self):
        try:
            return self.error / self.value
        except ZeroDivisionError:
            return -1

    @property
    def baseline_fit_abbreviation(self):
        if self.baseline:
            return self.baseline.fit_abbreviation
        else:
            return ""

    def __init__(self, name, detector):
        IsotopicMeasurement.__init__(self, name, detector)
        self.baseline = Baseline("{} bs".format(name), detector)

    def get_baseline_corrected_value(self, include_baseline_error=None, window=None, count=None):
        if include_baseline_error is None:
            include_baseline_error = self.include_baseline_error

        if window:
            ys = self.sniff.ys[-window:]
            # ddof=1 for unbiased sample std
            uv = ufloat(ys.mean(), ys.std(ddof=1), tag=self.name)
        elif count:
            uv = ufloat(self.sniff.ys[count], 0, tag=self.name)
        else:
            uv = self.uvalue

        if not include_baseline_error:
            # Subtract baseline value WITHOUT propagating its uncertainty.
            # Use nominal_value(b) so `nv` is signal_uvalue - scalar(b);
            # this preserves the correlation graph back to the signal
            # variables. (Previously wrapped `nv` in a fresh ufloat, which
            # silently destroyed the correlation graph and broke downstream
            # error-component attribution.)
            return uv - nominal_value(self.baseline.uvalue)
        return uv - self.baseline.uvalue

    def _get_baseline_fit_abbreviation(self):
        return self.baseline.fit_abbreviation


class Blank(BaseIsotope):
    pass


class Isotope(BaseIsotope):
    _kind = "signal"

    # blank = Instance(Blank)
    # background = Instance(Background)
    # sniff = Instance(Sniff)
    temporary_blank = None
    ic_factor = 1.0
    correct_for_blank = True
    # ic_factor = Either(Variable, AffineScalarFunc)

    age_error_component = 0.0
    # temporary_ic_factor = None
    # temporary_blank = Instance(Blank)
    decay_corrected = None

    discrimination = None
    interference_corrected_value = None
    blank_source = ""

    klass = 1

    def __init__(self, name, detector):
        BaseIsotope.__init__(self, name, detector)
        self.blank = Blank("{} bk".format(name), detector)
        self.sniff = Sniff(name, detector)
        self.background = Background("{} bg".format(name), detector)
        self.whiff = Whiff(name, detector)

    def set_detector_serial_id(self, sid):
        self.detector_serial_id = sid
        self.blank.detector_serial_id = sid
        self.sniff.detector_serial_id = sid
        self.baseline.detector_serial_id = sid

    def set_time_zero(self, time_zero_offset):
        self.time_zero_offset = time_zero_offset
        self.blank.time_zero_offset = time_zero_offset
        self.sniff.time_zero_offset = time_zero_offset
        self.baseline.time_zero_offset = time_zero_offset

    def set_units(self, units):
        self.units = units
        self.blank.units = units
        self.sniff.units = units
        self.baseline.units = units

    def get_filtered_data(self):
        return self.regressor.calculate_filtered_data()

    def revert_user_defined(self):
        self.blank._revert_user_defined()
        self.baseline._revert_user_defined()
        self._revert_user_defined()

    def get_ic_decay_corrected_value(self):
        if self.decay_corrected is not None:
            return self.decay_corrected
        else:
            return self.get_ic_corrected_value()

    def get_decay_corrected_value(self):
        if self.decay_corrected is not None:
            return self.decay_corrected
        else:
            return self.get_non_detector_corrected_value()
            # return self.get_interference_corrected_value()

    def get_interference_corrected_value(self):
        if self.interference_corrected_value is not None:
            return self.interference_corrected_value
        else:
            return ufloat(0, 0, tag=self.name)

    def get_intensity(self, **kw):
        """
        Return the discrimination and ic_factor corrected value.

        Blank/baseline/background subtraction happens earlier in
        `get_non_detector_corrected_value` (called via
        `get_disc_corrected_value`). The same correction order applies
        to all detectors — the previous "Minna bluff" Faraday-only
        deferred-blank hack has been removed.
        """
        ic = self.ic_factor if self.ic_factor is not None else 1.0
        return self.get_disc_corrected_value(**kw) * ic

    def get_disc_corrected_value(self, **kw):
        disc = self.discrimination if self.discrimination is not None else 1
        return self.get_non_detector_corrected_value(**kw) * disc

    def get_ic_corrected_value(self):
        ic = self.ic_factor if self.ic_factor is not None else 1.0
        return self.get_non_detector_corrected_value() * ic

    def no_baseline_error(self):
        v = self.get_baseline_corrected_value(include_baseline_error=False)

        if self.correct_for_blank:
            v = v - self.blank.value
        return v

    def get_non_detector_corrected_value(self, **kw):
        v = self.get_baseline_corrected_value(**kw)
        if self.correct_for_blank:
            v = v - self.blank.uvalue
        if self.background:
            v = v - self.background.uvalue
        return v

    def set_ublank(self, v):
        self.blank = Blank("{} bk".format(self.name), self.detector)
        self.blank.set_uvalue(v)

    def set_blank(self, v, e):
        self.set_ublank((v, e))

    def set_baseline(self, v, e):
        self.baseline = Baseline("{} bs".format(self.name), self.detector)
        self.baseline.set_uvalue((v, e))

    def _whiff_default(self):
        return Whiff()

    def _sniff_default(self):
        return Sniff()

    def _background_default(self):
        return Background()

    def _blank_default(self):
        return Blank()

    def __eq__(self, other):
        return self.get_baseline_corrected_value().__eq__(other)

    def __le__(self, other):
        return self.get_baseline_corrected_value().__le__(other)

    def __ge__(self, other):
        return self.get_baseline_corrected_value().__ge__(other)

    def __gt__(self, other):
        return self.get_baseline_corrected_value().__gt__(other)

    def __lt__(self, other):
        return self.get_baseline_corrected_value().__lt__(other)

    def __str__(self):
        try:
            return "{} {}".format(self.name, self.get_baseline_corrected_value())
        except (OverflowError, ValueError, AttributeError, TypeError) as e:
            return "{} {}".format(self.name, e)


# ============= EOF =============================================
