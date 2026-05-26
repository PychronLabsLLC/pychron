# ===============================================================================
# Copyright 2011 Jake Ross
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

# =============enthought library imports=======================

# ============= standard library imports ========================
import math

from numpy import array, asarray
from uncertainties import ufloat, umath, nominal_value, std_dev

from pychron.core.stats.core import calculate_weighted_mean
from pychron.core.utils import alpha_to_int
from pychron.processing.age_converter import converter
from pychron.processing.arar_constants import ArArConstants
from pychron.processing.plateau import Plateau
from pychron.pychron_constants import FLECK


def extract_isochron_xy(analyses):
    a39 = array([ai.get_interference_corrected_value("Ar39") for ai in analyses])
    a36 = array([ai.get_interference_corrected_value("Ar36") for ai in analyses])
    a40 = array([ai.get_interference_corrected_value("Ar40") for ai in analyses])
    try:
        xx = a39 / a40
        yy = a36 / a40
    except ZeroDivisionError:
        return
    return xx, yy, a39, a36, a40


def unpack_value_error(xx):
    """Split a sequence of ufloats into (nominals, std_devs)."""
    return (
        [nominal_value(xi) for xi in xx],
        [std_dev(xi) for xi in xx],
    )


def calculate_isochron(analyses, error_calc_kind, exclude=None, reg="NewYork", include_j_err=True):
    if exclude is None:
        exclude = []

    ref = analyses[0]
    args = extract_isochron_xy(analyses)
    if args is None:
        return
    xx, yy, a39, a36, a40 = args

    xs, xerrs = unpack_value_error(xx)
    ys, yerrs = unpack_value_error(yy)

    xds, xdes = unpack_value_error(a40)
    yns, ynes = unpack_value_error(a36)
    xns, xnes = unpack_value_error(a39)

    regx = isochron_regressor(ys, yerrs, xs, xerrs, xds, xdes, yns, ynes, xns, xnes, reg)
    regx.user_excluded = exclude

    reg = isochron_regressor(xs, xerrs, ys, yerrs, xds, xdes, xns, xnes, yns, ynes, reg)
    reg.user_excluded = exclude

    regx.error_calc_type = error_calc_kind
    reg.error_calc_type = error_calc_kind

    yint = ufloat(reg.get_intercept(), reg.get_intercept_error())
    try:
        r = 1 / ufloat(regx.get_intercept(), regx.get_intercept_error())
    except ZeroDivisionError:
        r = 0

    age = ufloat(0, 0)
    if r > 0:
        if include_j_err:
            j = ref.j
        else:
            j = (nominal_value(ref.j), 0)
        age = age_equation(j, r, arar_constants=ref.arar_constants)

    return age, yint, reg


def get_isochron_regressors(a40, a39, a36, kind="NewYork"):
    xx = a39 / a40
    yy = a36 / a40

    xs, xerrs = unpack_value_error(xx)
    ys, yerrs = unpack_value_error(yy)

    xds, xdes = unpack_value_error(a40)
    yns, ynes = unpack_value_error(a36)
    xns, xnes = unpack_value_error(a39)

    regx = isochron_regressor(ys, yerrs, xs, xerrs, xds, xdes, yns, ynes, xns, xnes, kind)
    reg = isochron_regressor(xs, xerrs, ys, yerrs, xds, xdes, xns, xnes, yns, ynes, kind)

    return reg, regx


def isochron_regressor(xs, xes, ys, yes, xds, xdes, xns, xnes, yns, ynes, reg="NewYork"):
    reg = reg.lower()
    if reg in ("newyork", "new_york"):
        from pychron.core.regression.new_york_regressor import NewYorkRegressor as klass
    elif reg == "york":
        from pychron.core.regression.new_york_regressor import YorkRegressor as klass
    else:
        from pychron.core.regression.new_york_regressor import (
            ReedYorkRegressor as klass,
        )

    reg = klass(
        xs=xs,
        ys=ys,
        xserr=xes,
        yserr=yes,
        xds=xds,
        xdes=xdes,
        xns=xns,
        xnes=xnes,
        yns=yns,
        ynes=ynes,
    )
    reg.calculate()
    return reg


def calculate_plateau_age(
    ages,
    errors,
    k39,
    steps,
    kind="inverse_variance",
    method=FLECK,
    options=None,
    excludes=None,
):
    """
    ages: list of ages
    errors: list of corresponding  1sigma errors
    k39: list of 39ArK signals
    steps: list of step labels

    return age, error
    """
    if options is None:
        options = {}

    ages = asarray(ages)
    errors = asarray(errors)
    k39 = asarray(k39)

    fixed_steps = options.get("fixed_steps", False)

    p = Plateau(
        ages=ages,
        errors=errors,
        signals=k39,
        excludes=excludes,
        overlap_sigma=options.get("overlap_sigma", 2),
        nsteps=options.get("nsteps", 3),
        gas_fraction=options.get("gas_fraction", 50),
    )
    pidx = None
    if fixed_steps and (fixed_steps[0] or fixed_steps[1]):
        steps = [s.upper() for s in steps]
        sstep, estep = fixed_steps
        sstep, estep = sstep.upper(), estep.upper()
        if not sstep:
            sidx = 0
        else:
            try:
                sidx = steps.index(sstep)
            except ValueError:
                sidx = None

        if sidx is not None:
            n = ages.shape[0] - 1
            if not estep:
                eidx = n
            else:
                try:
                    eidx = steps.index(estep)
                except ValueError:
                    eidx = None
            if eidx is not None:
                sidx, eidx = min(sidx, eidx), min(max(sidx, eidx), n)
                pidx = (sidx, eidx) if sidx < n else None

    if pidx is None:
        pidx = p.find_plateaus(method)

    if pidx:
        sx = slice(pidx[0], pidx[1] + 1)
        plateau_ages = ages[sx]
        plateau_errors = errors[sx]
        if kind == "vol_fraction":
            # External-weight (39ArK) weighted mean:
            #   wm = Σ(wi*ai) / Σwi
            #   var(wm) = Σ(wi^2 * σi^2) / (Σwi)^2
            weights = k39[sx]
            sw = weights.sum()
            wm = (weights * plateau_ages).sum() / sw
            we = ((weights**2 * plateau_errors**2).sum()) ** 0.5 / sw
        else:
            wm, we = calculate_weighted_mean(plateau_ages, plateau_errors)

        return wm, we, pidx


def calculate_flux(f, age, arar_constants=None, lambda_k=None):
    """
    #rad40: radiogenic 40Ar
    #k39: 39Ar from potassium
    f: F value rad40Ar/39Ar
    age: age of monitor in years

    solve age equation for J
    """
    if isinstance(f, (list, tuple)):
        f = ufloat(*f)

    if isinstance(age, (list, tuple)):
        age = ufloat(*age)
    try:
        if not lambda_k:
            if arar_constants is None:
                arar_constants = ArArConstants()
            lambda_k = nominal_value(arar_constants.lambda_k)

        j = (umath.exp(age * lambda_k) - 1) / f
        return j
    except ZeroDivisionError:
        return ufloat(1, 0)


def calculate_decay_time(dc, f):
    return math.log(f) / dc


# Maximum allowed dc * time product before we treat the inputs as a likely
# unit mismatch. exp(700) overflows float64; ar37/ar39 with typical decay
# windows produce dc·t ~ 0.01 to ~20. A factor of 50 is well clear of any
# realistic geochronology scenario but well below the overflow threshold.
_MAX_DECAY_EXPONENT = 50.0


def _check_decay_units(dc37, dc39, segments):
    """
    Sanity-check that dc * t products are physical.

    `calculate_arar_decay_factors` accepts time arguments in whatever unit
    matches the decay constants. Lambda_Ar37 / lambda_Ar39 in
    ArArConstants are PER DAY, so segment durations and dti values must be
    in days. Passing seconds (×86400) silently overflows `math.exp`. This
    guard raises a clear ValueError instead.
    """
    for pi, ti, dti, _, _ in segments:
        for dc, label in ((dc37, "dc37"), (dc39, "dc39")):
            product = abs(dc * max(abs(ti), abs(dti)))
            if product > _MAX_DECAY_EXPONENT:
                raise ValueError(
                    "calculate_arar_decay_factors: {} * t = {:.3g} is too "
                    "large to be physical. Decay constants and segment "
                    "times must share the same unit (lambda_Ar37/39 are "
                    "per-day → segments must be in days, not seconds).".format(label, product)
                )


def calculate_arar_decay_factors_dalrymple(dc37, dc39, segments):
    """
    Dalrymple et al. (1981) decay-factor formulation (alternative to M&H).

    See `calculate_arar_decay_factors` for the unit convention — all time
    arguments must share units with `dc37`/`dc39`.
    """
    _check_decay_units(dc37, dc39, segments)
    try:
        tpower = sum(pi * ti for pi, ti, _, _, _ in segments)
        df37 = 0.0
        df39 = 0.0
        for pi, ti, ti_p, _, _ in segments:
            pti = (pi * ti) / tpower
            e37 = math.exp(dc37 * ti_p)
            e39 = math.exp(dc39 * ti_p)
            df37 += pti * (ti * dc37 * e37) / (1 - math.exp(-dc37 * ti))
            df39 += pti * (ti * dc39 * e39) / (1 - math.exp(-dc39 * ti))
    except ZeroDivisionError:
        return 1.0, 1.0
    return df37, df39


def calculate_arar_decay_factors(dc37, dc39, segments, use_mh=True):
    """
    Compute Ar37 and Ar39 decay factors over an irradiation history.

    McDougall and Harrison p.75 eq 3.22 (default, `use_mh=True`):
        df = Σ(pi · ti) / Σ(pi · (1 - exp(-dc·ti)) / (dc · exp(dc·dti)))

    ti = end of irradiation segment_i minus start of segment_i (duration).
    dti = analysis_time minus end of irradiation segment_i.
    Dalrymple et al. 1981 p.34 shows that decay during irradiation is
    handled by their equation 39, so using the end of the segment for
    `dti` is correct.

    Units:
        dc37 / dc39 = decay constants for Ar37 / Ar39. As supplied by
        `pychron.processing.arar_constants.ArArConstants` these are
        **per day** (Ar37 t½ ≈ 35.04 d; Ar39 t½ ≈ 269 a).
        Segments must therefore use **days** for both `ti` (duration)
        and `dti` (time since end of segment).

    Passing seconds instead of days (or any other unit mismatch) is
    silently catastrophic — `exp(dc·t)` overflows. A ValueError is raised
    instead if any `dc·t` product exceeds {} (well above any physical
    scenario, well below `exp` overflow).

    Parameters
    ----------
    dc37, dc39 : float
        Decay constants for Ar37 / Ar39 (per-day if using ArArConstants
        defaults).
    segments : iterable of (power, duration, time_since_end, _, _) tuples
        Irradiation segments. Pass `None` for no irradiation (returns
        unity factors).
    use_mh : bool
        If True, use M&H. If False, use Dalrymple et al. 1981.
    """.format(_MAX_DECAY_EXPONENT)
    if segments is None:
        return 1.0, 1.0

    if not use_mh:
        return calculate_arar_decay_factors_dalrymple(dc37, dc39, segments)

    _check_decay_units(dc37, dc39, segments)

    # Single pass: accumulate tpower + both M&H denominators together.
    tpower = 0.0
    b = 0.0
    c = 0.0
    for pi, ti, dti, _, _ in segments:
        tpower += pi * ti
        b += pi * (1 - math.exp(-dc37 * ti)) / (dc37 * math.exp(dc37 * dti))
        c += pi * (1 - math.exp(-dc39 * ti)) / (dc39 * math.exp(dc39 * dti))

    df37 = tpower / b if b else 1.0
    df39 = tpower / c if c else 1.0
    return df37, df39


def abundance_sensitivity_correction(isos, abundance_sensitivity):
    s40, s39, s38, s37, s36 = isos
    # correct for abundance sensitivity
    # assumes symmetric and equal abundant sens for all peaks
    n40 = s40 - abundance_sensitivity * (s39 + s39)
    n39 = s39 - abundance_sensitivity * (s40 + s38)
    n38 = s38 - abundance_sensitivity * (s39 + s37)
    n37 = s37 - abundance_sensitivity * (s38 + s36)
    n36 = s36 - abundance_sensitivity * (s37 + s37)
    return [n40, n39, n38, n37, n36]


def apply_fixed_k3739(a39, pr, fixed_k3739):
    """
    Deconvolve K and Ca from a39 using a fixed K37/K39 ratio.

    x = ca37/k39
    y = ca37/ca39
    T = a39 = ca39 + k39
      = ca37/y + ca37/x
    → ca37 = (T*x*y) / (x+y)
    """
    x = fixed_k3739
    ca3937 = pr.get("Ca3937", 0)
    try:
        y = 1 / ca3937
    except ZeroDivisionError:
        y = 1

    ca37 = (a39 * x * y) / (x + y)
    ca39 = ca3937 * ca37
    k39 = a39 - ca39
    k37 = x * k39
    return ca37, ca39, k37, k39


def interference_corrections(a39, a37, production_ratios, arar_constants=None, fixed_k3739=False):
    if production_ratios is None:
        production_ratios = {}

    if arar_constants is None:
        arar_constants = ArArConstants()

    pr = production_ratios
    ca3937 = pr.get("Ca3937", 0)
    k3739 = pr.get("K3739", 0)

    if arar_constants.k3739_mode.lower() == "normal" and not fixed_k3739:
        k39 = (a39 - ca3937 * a37) / (1 - k3739 * ca3937)
        k37 = k3739 * k39
        ca37 = a37 - k37
        ca39 = ca3937 * ca37
    else:
        if not fixed_k3739:
            fixed_k3739 = arar_constants.fixed_k3739
        ca37, ca39, k37, k39 = apply_fixed_k3739(a39, pr, fixed_k3739)

    k38 = pr.get("K3839", 0) * k39
    if not arar_constants.allow_negative_ca_correction:
        ca37 = max(ufloat(0, 0), ca37)
    ca36 = pr.get("Ca3637", 0) * ca37
    ca38 = pr.get("Ca3837", 0) * ca37

    return k37, k38, k39, ca36, ca37, ca38, ca39


def calculate_atmospheric(
    a38, a36, k38, ca38, ca36, decay_time, production_ratios=None, arar_constants=None
):
    """
    McDougall and Harrison
    Roddick 1983
    Foland 1993

    calculate atm36, cl36, cl38

    # starting with the following equations
    atm36 = a36 - ca36 - cl36

    m = cl3638*lambda_cl36*decay_time
    cl36 = cl38 * m

    cl38 = a38 - k38 - ca38 - ar38atm
    ar38atm = atm3836 * atm36

    # rearranging to solve for atm36
    cl38 = a38  - k38 - c38 - atm3836 * atm36

    cl36 = m * (a38  - k38 - ca38 - atm3836 * atm36)
         = m (a38  - k38 - ca38) - m * atm3836 * atm36
    atm36 = a36 - ca36 - m (a38  - k38 - ca38) + m * atm3836 * atm36
    atm36 - m * atm3836 * atm36 =  a36 - ca36 - m (a38  - k38 - ca38)
    atm36 * (1 - m*atm3836) = a36 - ca36 - m (a38  - k38 - ca38)
    atm36 = (a36 - ca36 - m (a38  - k38 - c38))/(1 - m*atm3836)


    """
    if production_ratios is None:
        production_ratios = {}

    if arar_constants is None:
        arar_constants = ArArConstants()

    pr = production_ratios

    # Preserve uncertainties on lambda_Cl36 and atm3836 — previously stripped
    # via nominal_value, which silently underestimated cl/atm errors.
    lambda_cl36 = ufloat(
        nominal_value(arar_constants.lambda_Cl36),
        std_dev(arar_constants.lambda_Cl36),
        tag="lambda_Cl36",
    )
    atm3836 = ufloat(
        nominal_value(arar_constants.atm3836),
        std_dev(arar_constants.atm3836),
        tag="atm3836",
    )

    m = pr.get("Cl3638", 0) * lambda_cl36 * decay_time
    atm36 = (a36 - ca36 - m * (a38 - k38 - ca38)) / (1 - m * atm3836)
    atm38 = atm3836 * atm36
    cl38 = a38 - atm38 - k38 - ca38
    cl36 = cl38 * m

    return atm36, atm38, cl36, cl38


def calculate_cosmogenic_components(c36, c38, arar_constants):
    """
    Two-component mixing between solar/target and cosmogenic 38/36.

    rm = measured 38/36 ratio
    rs = solar/target (atmospheric-like) 38/36 ratio
    rc = cosmogenic 38/36 ratio
    fs = solar fraction, fc = cosmogenic fraction (fs + fc = 1)

    rm = fs*rs + fc*rc  →  fs = (rc - rm) / (rc - rs)
    """
    rm = c38 / c36
    rs = arar_constants.solar3836
    rc = arar_constants.cosmo3836

    fs = (rc - rm) / (rc - rs)
    fc = 1 - fs

    noncosmo38 = fs * c38
    cosmo38 = c38 - noncosmo38
    cosmo36 = fc * c36
    noncosmo36 = c36 - cosmo36

    return cosmo36, cosmo38, noncosmo36, noncosmo38


def calculate_f(isotopes, decay_time, interferences=None, arar_constants=None, fixed_k3739=False):
    """
    Isotope values must already be corrected for blank, baseline,
    (background), ic_factor, (discrimination), and Ar37/Ar39 decay.
    """
    if interferences is None:
        interferences = {}
    if arar_constants is None:
        arar_constants = ArArConstants()

    a40, a39, a38, a37, a36 = isotopes
    use_cosmo = arar_constants.use_cosmogenic_correction

    # Build the trapped-air 40/36 ratio once; both inner passes share it.
    trapped_4036 = ufloat(nominal_value(arar_constants.atm4036), std_dev(arar_constants.atm4036))
    trapped_4036.tag = "trapped_4036"

    def calc_f(pr):
        k37, k38, k39, ca36, ca37, ca38, ca39 = interference_corrections(
            a39, a37, pr, arar_constants, fixed_k3739
        )
        atm36, atm38, cl36, cl38 = calculate_atmospheric(
            a38, a36, k38, ca38, ca36, decay_time, pr, arar_constants
        )

        cosmo36 = cosmo38 = None
        if use_cosmo:
            cosmo36, cosmo38, atm36, atm38 = calculate_cosmogenic_components(
                atm36, atm38, arar_constants
            )

        atm40 = atm36 * trapped_4036
        k40 = k39 * pr.get("K4039", 0)
        rad40 = a40 - atm40 - k40
        try:
            ff = rad40 / k39
        except ZeroDivisionError:
            ff = ufloat(1.0, 0)
        try:
            rp = rad40 / a40 * 100
        except ZeroDivisionError:
            rp = ufloat(0, 0)

        nar = {
            "k40": k40,
            "ca39": ca39,
            "k38": k38,
            "ca38": ca38,
            "cl38": cl38,
            "k37": k37,
            "ca37": ca37,
            "ca36": ca36,
            "cl36": cl36,
            "cosmo38": cosmo38,
            "cosmo36": cosmo36,
        }
        comp = {
            "rad40": rad40,
            "a40": a40,
            "radiogenic_yield": rp,
            "ca37": ca37,
            "ca39": ca39,
            "ca36": ca36,
            "k39": k39,
            "atm40": atm40,
        }
        ifc = {"Ar40": a40 - k40, "Ar39": k39, "Ar38": a38, "Ar37": a37, "Ar36": atm36}
        return ff, nar, comp, ifc

    # f_wo_irrad uses zero-uncertainty interference ratios so its error
    # excludes the irradiation-ratio component.
    pr_zero = {k: ufloat(nominal_value(v), std_dev=0, tag=v.tag) for k, v in interferences.items()}
    f_wo_irrad, _, _, _ = calc_f(pr_zero)
    f, non_ar_isotopes, computed, interference_corrected = calc_f(interferences)

    return f, f_wo_irrad, non_ar_isotopes, computed, interference_corrected


def convert_age(uage, original_monitor_age, original_lambda_k, new_monitor_age, new_lambda_k):
    converter.setup(original_monitor_age, original_lambda_k)
    if new_monitor_age is None:
        age, err = converter.convert(nominal_value(uage), std_dev(uage))
        uage = ufloat(age, err, tag=uage.tag)

    return uage


def age_equation(j, f, include_decay_error=False, lambda_k=None, arar_constants=None):
    if isinstance(j, tuple):
        j = ufloat(*j)
    elif isinstance(j, str):
        j = ufloat(j)

    if isinstance(f, tuple):
        f = ufloat(*f)
    elif isinstance(f, str):
        f = ufloat(f)

    if not lambda_k:
        if arar_constants is None:
            arar_constants = ArArConstants()
        lambda_k = arar_constants.lambda_k

    if arar_constants is None:
        arar_constants = ArArConstants()

    if not include_decay_error:
        lambda_k = nominal_value(lambda_k)
    try:
        # lambda is defined in years, so age is in years
        age = lambda_k**-1 * umath.log(1 + j * f)

        return arar_constants.scale_age(age, current="a")
    except (ValueError, TypeError):
        return ufloat(0, 0)


# ===============================================================================
# non-recursive
# ===============================================================================


def calculate_error_F(signals, F, k4039, ca3937, ca3637):
    """
    McDougall and Harrison
    p92 eq 3.43

    """

    m40, m39, m38, m37, m36 = signals
    G = m40 / m39
    B = m36 / m39
    D = m37 / m39
    C1 = 295.5
    C2 = ca3637.nominal_value
    C3 = k4039.nominal_value
    C4 = ca3937.nominal_value

    ssD = D.std_dev**2
    ssB = B.std_dev**2
    ssG = G.std_dev**2
    G = G.nominal_value
    B = B.nominal_value
    D = D.nominal_value

    ssF = ssG + C1**2 * ssB + ssD * (C4 * G - C1 * C4 * B + C1 * C2) ** 2
    return ssF**0.5


def calculate_error_t(F, ssF, j, ssJ):
    """
    McDougall and Harrison
    p92 eq. 3.43
    """
    JJ = j * j
    FF = F * F
    constants = ArArConstants()
    ll = constants().lambdak.nominal_value**2
    sst = (JJ * ssF + FF * ssJ) / (ll * (1 + F * j) ** 2)
    return sst**0.5


def calculate_fractional_loss(t, temp, a, model="plane", material="kfeldspar"):
    """

    :param t: years
    :param a: mm
    :return:
    """

    r = 1.9872036e-3  # kcal/(K*mol)

    # convert a (mm) to cm
    a /= 10
    # convert t (years) to seconds
    t *= 365.25 * 24 * 3600

    # convert temp (C) to Kelvin
    temp += 273.15

    if material == "kfeldspar":
        d_0 = 0.0098  # cm/s**2
        ea = 43.8  # kcal/mol

    d = d_0 * math.exp(-ea / (r * temp))

    if model == "plane":
        f = 2 / math.pi**0.5 * (d * t / a**2) ** 0.5
        if 1 >= f >= 0.45:
            f = 1 - (8 / math.pi**2) * math.exp(-math.pi**2 * d * t / (4 * a**2))

    return f


# ============= EOF =====================================
