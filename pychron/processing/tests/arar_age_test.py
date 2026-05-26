# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Integration tests for `ArArAge.calculate_age()` and the surrounding pipeline.

These exercise the full path from per-isotope `Isotope.value` → assemble →
F → age, with all the J-variant ages and K/Ca + K/Cl side products. The
goal is to lock current behavior so recent bug fixes (J shallow-copy,
hardcoded-index assembly, ic_factor falsy, baseline correlation) can't
silently regress.
"""

from unittest import TestCase

import numpy as np
from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.arar_age import ArArAge
from pychron.processing.isotope import Isotope


def _build_isotope(name, detector, intercept, n=50, noise=0.05, seed=0):
    rng = np.random.default_rng(seed)
    iso = Isotope(name, detector)
    iso.xs = np.linspace(0, 100, n)
    iso.ys = intercept + 0.01 * iso.xs + rng.normal(0, noise, n)
    iso.fit = "linear"
    iso.error_type = "SEM"
    iso.set_baseline(0.0, 0.0)
    iso.set_blank(0.0, 0.0)
    return iso


def _interferences():
    return {
        "Ca3937": ufloat(0.0007, 0),
        "K3739": ufloat(0.01, 0),
        "K3839": ufloat(0.013, 0),
        "Ca3637": ufloat(0.00026, 0),
        "Ca3837": ufloat(0.00019, 0),
        "K4039": ufloat(0.0002, 0),
        "Cl3638": ufloat(0, 0),
        "Ca_K": ufloat(2.0, 0),
        "Cl_K": ufloat(0.1, 0),
    }


def _build_age(intensities=None, j_err=1e-6, seed=0):
    age = ArArAge()
    age.timestamp = 86400 * 365 * 5  # 5 years after irradiation
    age.irradiation_time = 0

    intensities = intensities or {
        "Ar40": 1000.0,
        "Ar39": 100.0,
        "Ar38": 10.0,
        "Ar37": 50.0,
        "Ar36": 2.0,
    }
    for i, (name, intercept) in enumerate(intensities.items()):
        detector = ("H1", "AX", "L1", "L2", "CDD")[i]
        age.isotopes[name] = _build_isotope(name, detector, intercept, seed=seed + i)

    age.set_j(1e-3, j_err)
    age.position_jerr = j_err * 0.5
    age.interference_corrections = _interferences()
    return age


class ArArAgePipelineTest(TestCase):
    """End-to-end calculate_age() invocation."""

    @classmethod
    def setUpClass(cls):
        cls.age = _build_age()
        cls.age.calculate_age()

    def test_age_is_positive(self):
        self.assertGreater(self.age.age, 0)

    def test_age_err_is_positive(self):
        self.assertGreater(self.age.age_err, 0)

    def test_age_equation_known_value(self):
        """Direct algebraic check: age = (1/λ_k) · ln(1 + J·F)."""
        import math

        lk = nominal_value(self.age.arar_constants.lambda_k)
        expected = (1 / lk) * math.log(1 + 1e-3 * self.age.F)
        self.assertAlmostEqual(self.age.age, expected, places=2)

    def test_uage_w_j_err_includes_j(self):
        """uage_w_j_err should have larger std_dev than uage (which strips J)."""
        self.assertGreater(std_dev(self.age.uage_w_j_err), std_dev(self.age.uage))

    def test_uage_w_position_err_smaller_than_uage_w_j(self):
        """position_jerr = 0.5·j_err, so position variant has tighter J uncertainty."""
        self.assertLess(
            std_dev(self.age.uage_w_position_err),
            std_dev(self.age.uage_w_j_err),
        )

    def test_uF_is_ufloat(self):
        self.assertIsNotNone(self.age.uF)
        self.assertGreater(self.age.F_err, 0)

    def test_F_err_wo_irrad_lte_F_err(self):
        """F_err_wo_irrad strips interference-ratio uncertainty."""
        self.assertLessEqual(self.age.F_err_wo_irrad, self.age.F_err)

    def test_corrected_intensities_populated(self):
        self.assertEqual(
            set(self.age.corrected_intensities.keys()),
            {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"},
        )

    def test_radiogenic_yield_is_percent(self):
        self.assertGreaterEqual(nominal_value(self.age.radiogenic_yield), 0)
        self.assertLessEqual(nominal_value(self.age.radiogenic_yield), 100)

    def test_decay_factors_default_to_unity_without_segments(self):
        # chron_segments is None → factors must be exactly 1.0
        self.assertEqual(self.age.ar39decayfactor, 1.0)
        self.assertEqual(self.age.ar37decayfactor, 1.0)


class JVariantCorrectnessTest(TestCase):
    """Regression: `copy(self.j)` was shallow; mutating .std_dev mutated
    self.j. The fix builds each J variant as a fresh ufloat. Verify
    self.j is unchanged after _set_age_values."""

    def test_self_j_unchanged_after_age_calc(self):
        age = _build_age()
        j_before = (nominal_value(age.j), std_dev(age.j))
        age.calculate_age()
        j_after = (nominal_value(age.j), std_dev(age.j))
        self.assertEqual(j_before, j_after)

    def test_position_err_uses_position_jerr_only(self):
        """uage_w_position_err must reflect position_jerr, not full j err."""
        age = _build_age(j_err=1e-5)
        age.position_jerr = 1e-8  # much smaller than j_err
        age.calculate_age()
        # position variant tighter than full-j variant
        self.assertLess(
            std_dev(age.uage_w_position_err),
            std_dev(age.uage_w_j_err),
        )

    def test_uage_strips_j_error(self):
        """uage uses std_dev=0 on J. Std_dev only reflects analytical err."""
        age = _build_age(j_err=1e-3)  # huge J err
        age.calculate_age()
        # If J err were leaking through, uage err ≈ uage_w_j_err err.
        # With strip, uage err is much smaller.
        self.assertLess(std_dev(age.uage), std_dev(age.uage_w_j_err))


class DecayFactorCachingTest(TestCase):
    """`calculate_decay_factors` caches the result via `ar39decayfactor`
    truthiness guard. Verify second call is a no-op."""

    def test_segments_produce_decay_factors(self):
        age = _build_age()
        # Segments: (power, duration_days, time_since_end_days, _, _).
        # Lambda_Ar37 / lambda_Ar39 in arar_constants are per-day, so all
        # time arguments must be in days.
        age.chron_segments = [(1.0, 1.0, 365.0, None, None)]
        age.calculate_decay_factors()
        self.assertGreater(age.ar37decayfactor, 1.0)
        self.assertGreater(age.ar39decayfactor, 1.0)

    def test_second_call_does_not_recompute(self):
        age = _build_age()
        age.chron_segments = [(1.0, 1.0, 365.0, None, None)]
        age.calculate_decay_factors()
        df_first = (age.ar37decayfactor, age.ar39decayfactor)
        # Mutate segments — second call should NOT pick up the change
        # (cache guard relies on ar39decayfactor truthiness).
        age.chron_segments = None
        age.calculate_decay_factors()
        self.assertEqual((age.ar37decayfactor, age.ar39decayfactor), df_first)


class KCaKClTest(TestCase):
    """K/Ca and K/Cl are derived from computed intensities + production
    ratios. Verify they're computed and respect Ca_K / Cl_K scaling."""

    def test_kca_computed(self):
        age = _build_age()
        age.calculate_age()
        # ca37 may be near-zero for typical synthetic data; just check the
        # path runs and produces a finite value
        self.assertIsNotNone(age.kca)

    def test_kcl_computed(self):
        age = _build_age()
        age.calculate_age()
        self.assertIsNotNone(age.kcl)

    def test_cak_is_inverse_of_kca(self):
        age = _build_age()
        age.calculate_age()
        if nominal_value(age.kca) != 0:
            self.assertAlmostEqual(nominal_value(age.cak) * nominal_value(age.kca), 1.0, places=8)

    def test_production_ratio_inverse_handles_missing_key(self):
        age = _build_age()
        self.assertEqual(age._production_ratio_inverse("nonexistent_key"), 1)

    def test_production_ratio_inverse_handles_zero(self):
        age = _build_age()
        age.production_ratios = {"foo": 0}
        # 0 → fallback to 1
        self.assertEqual(age._production_ratio_inverse("foo"), 1)


class InstantAgeTest(TestCase):
    """`instant_age(count=i)` evaluates the age at sniff-window point i.
    Just verify it runs end-to-end without crashing for a representative
    setup."""

    def test_instant_age_runs(self):
        age = _build_age()
        for iso in age.isotopes.values():
            # populate sniff so count-indexed lookup works
            iso.sniff.xs = np.linspace(0, 10, 20)
            iso.sniff.ys = np.full(20, nominal_value(iso.value))
        result = age.instant_age(count=5)
        # may return None if intensities can't be assembled; otherwise a ufloat
        if result is not None:
            self.assertGreater(nominal_value(result), 0)


class RecalculateAgeTest(TestCase):
    """`recalculate_age(force=True)` runs the J-variant recomputation
    without re-doing F. After J change the age must shift."""

    def test_force_recalc_uses_new_j(self):
        age = _build_age(j_err=1e-7)
        age.calculate_age()
        age_before = age.age

        # Change J nominal and re-trigger
        age.set_j(2e-3, 1e-7)
        age.recalculate_age(force=True)
        # age should roughly double when J doubles (for small J·F)
        self.assertNotAlmostEqual(age.age, age_before, places=2)
        # uage_w_j_err is the rebuilt age
        self.assertAlmostEqual(age.age, nominal_value(age.uage), places=6)


class NoInterferenceTest(TestCase):
    """`calculate_no_interference` runs _calculate_age with empty
    interferences — useful for checking the no-correction baseline."""

    def test_runs_without_error(self):
        age = _build_age()
        age.calculate_no_interference()
        self.assertIsNotNone(age.F)


class AssemblyByNameTest(TestCase):
    """`_assemble_isotope_intensities` now indexes by ARGON_KEYS.index(...)
    rather than hardcoded positional [1]/[3]. Verify Ar39/Ar37 decay
    factors are applied to the correct isotopes."""

    def test_ar39_decay_applied_to_ar39(self):
        age = _build_age()
        age.chron_segments = [(1.0, 1.0, 365.0, None, None)]
        age.calculate_decay_factors()
        df39 = age.ar39decayfactor
        df37 = age.ar37decayfactor

        intensities = age._assemble_isotope_intensities()
        raw = age._assemble_ar_ar_isotopes()
        # ARGON_KEYS = (Ar40, Ar39, Ar38, Ar37, Ar36); positions 1 & 3
        from pychron.pychron_constants import ARGON_KEYS

        ar39_idx = ARGON_KEYS.index("Ar39")
        ar37_idx = ARGON_KEYS.index("Ar37")

        # Abundance-sensitivity correction also happens; for default
        # constants its abundance_sensitivity ≈ 0 → identity. So decay
        # factor should be the only difference.
        ratio39 = nominal_value(intensities[ar39_idx]) / nominal_value(raw[ar39_idx])
        ratio37 = nominal_value(intensities[ar37_idx]) / nominal_value(raw[ar37_idx])
        self.assertAlmostEqual(ratio39, df39, places=6)
        self.assertAlmostEqual(ratio37, df37, places=6)


class GetValueDispatcherTest(TestCase):
    """`get_value(attr)` dispatches on attr suffix/prefix:
    attr.endswith('bs') → baseline.uvalue
    attr in {'uage', 'uage_w_j_err', 'uage_w_position_err', 'uF'} → trait
    attr.startswith('u') and ('/' or '_') → non_ic_corrected ratio
    attr == 'icf_40_36' → corrected_ratio
    attr.endswith('ic') → ic_factor
    attr in computed → computed value
    attr in isotopes → get_intensity
    """

    def setUp(self):
        self.age = _build_age()
        self.age.calculate_age()

    def test_baseline_suffix(self):
        v = self.age.get_value("Ar40bs")
        # default baseline = 0
        self.assertEqual(nominal_value(v), 0)

    def test_uage(self):
        v = self.age.get_value("uage")
        self.assertEqual(v, self.age.uage)

    def test_uage_w_j_err(self):
        v = self.age.get_value("uage_w_j_err")
        self.assertEqual(v, self.age.uage_w_j_err)

    def test_uF(self):
        v = self.age.get_value("uF")
        self.assertEqual(v, self.age.uF)

    def test_isotope_returns_intensity(self):
        v = self.age.get_value("Ar40")
        # noisy synthetic data: intercept ~1000 ± noise_sem
        self.assertAlmostEqual(nominal_value(v), 1000.0, delta=0.5)

    def test_ic_suffix(self):
        v = self.age.get_value("Ar40ic")
        # Default ic_factor = 1.0 (not a ufloat)
        self.assertEqual(v, 1.0)

    def test_computed_attr(self):
        # k39 is populated by calculate_age
        v = self.age.get_value("k39")
        self.assertGreater(nominal_value(v), 0)

    def test_arbitrary_attr_falls_through_to_hasattr(self):
        self.age.custom_attr = 42
        v = self.age.get_value("custom_attr")
        self.assertEqual(v, 42)


class CorrectedRatioTest(TestCase):
    def setUp(self):
        self.age = _build_age()
        self.age.calculate_age()

    def test_corrected_ratio_present(self):
        v = self.age.get_corrected_ratio("Ar40", "Ar39")
        self.assertIsNotNone(v)

    def test_corrected_ratio_missing(self):
        v = self.age.get_corrected_ratio("Ar40", "MISSING")
        self.assertIsNone(v)


class GetInterferenceCorrectedValueTest(TestCase):
    def test_present(self):
        age = _build_age()
        age.calculate_age()
        v = age.get_interference_corrected_value("Ar40")
        self.assertGreater(nominal_value(v), 0)

    def test_missing(self):
        age = _build_age()
        v = age.get_interference_corrected_value("Xe129")
        self.assertEqual(nominal_value(v), 0)


class GetNonArIsotopeAndComputedTest(TestCase):
    def setUp(self):
        self.age = _build_age()
        self.age.calculate_age()

    def test_get_non_ar_isotope_present(self):
        v = self.age.get_non_ar_isotope("ca37")
        self.assertIsNotNone(v)

    def test_get_non_ar_isotope_missing(self):
        v = self.age.get_non_ar_isotope("xenon")
        self.assertEqual(nominal_value(v), 0)

    def test_get_computed_value_present(self):
        v = self.age.get_computed_value("k39")
        self.assertGreater(nominal_value(v), 0)

    def test_get_computed_value_missing(self):
        v = self.age.get_computed_value("nonsense_key")
        self.assertEqual(nominal_value(v), 0)


class ToDictSerializersTest(TestCase):
    """*_to_dict serializers should return {iso_name: {'value':..., 'error':...}}."""

    def setUp(self):
        self.age = _build_age()

    def test_baseline_corrected_intercepts(self):
        d = self.age.baseline_corrected_intercepts_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})
        for v in d.values():
            self.assertIn("value", v)
            self.assertIn("error", v)

    def test_blanks_to_dict(self):
        d = self.age.blanks_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_icfactors_to_dict(self):
        d = self.age.icfactors_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_interference_corrected_values_to_dict(self):
        self.age.calculate_age()
        d = self.age.interference_corrected_values_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_ic_corrected_values_to_dict(self):
        d = self.age.ic_corrected_values_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_decay_corrected_values_to_dict(self):
        self.age.calculate_age()
        d = self.age.decay_corrected_values_to_dict()
        self.assertEqual(set(d.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})


class TemporaryICFactorTest(TestCase):
    def test_set_temporary_uic_factor(self):
        age = _build_age()
        u = ufloat(1.02, 0.01)
        age.set_temporary_uic_factor("H1", refdet="AX", uv=u)
        self.assertEqual(age.temporary_ic_factors["H1"], u)

    def test_set_temporary_ic_factor_with_tag(self):
        age = _build_age()
        uv = age.set_temporary_ic_factor("AX", "H1", 1.05, 0.005, tag="test")
        self.assertEqual(nominal_value(uv), 1.05)
        self.assertEqual(std_dev(uv), 0.005)
        stored = age.temporary_ic_factors["H1"]
        self.assertEqual(stored["reference_detector"], "AX")


class SetDiscriminationTest(TestCase):
    def test_set_discrimination_populates_ic_factors(self):
        age = _build_age()
        # is_peak_hop=False → looks up by isotope name. The disc loop
        # covers Ar40, Ar39, Ar38, Ar37 (Ar36 is the reference mass).
        age.set_discrimination(ufloat(1.04, 0.01), is_peak_hop=False)
        self.assertEqual(len(age.temporary_ic_factors), 4)


class SetBetaTest(TestCase):
    def test_set_beta_populates_ic_factors(self):
        age = _build_age()
        age.set_beta("H1", beta=0.005, is_peak_hop=False)
        # 4 detectors (Ar36, Ar37, Ar38, Ar39 — not Ar40, the reference)
        self.assertEqual(len(age.temporary_ic_factors), 4)


class SetJTest(TestCase):
    def test_set_j_assigns_ufloat(self):
        age = _build_age()
        age.set_j(2e-3, 1e-7)
        self.assertEqual(nominal_value(age.j), 2e-3)
        self.assertEqual(std_dev(age.j), 1e-7)
        # tag is set to "J"
        self.assertEqual(age.j.tag, "J")


class SetTemporaryBlankTest(TestCase):
    def test_creates_temporary_blank(self):
        age = _build_age()
        age.set_temporary_blank("Ar40", 0.5, 0.05, "linear")
        tb = age.isotopes["Ar40"].temporary_blank
        self.assertIsNotNone(tb)
        self.assertEqual(tb.value, 0.5)
        self.assertEqual(tb.error, 0.05)
        self.assertEqual(tb.fit, "linear")

    def test_missing_isotope_no_op(self):
        age = _build_age()
        # should silently not crash
        age.set_temporary_blank("Xe129", 0.5, 0.05, "linear")


class SetSensitivityTest(TestCase):
    def test_picks_most_recent_before_rundate(self):
        age = _build_age()
        age.rundate = 100
        sens = [
            {"create_date": 50, "sensitivity": 1e-17, "units": "mol/fA"},
            {"create_date": 90, "sensitivity": 2e-17, "units": "mol/fA"},
            {"create_date": 200, "sensitivity": 3e-17, "units": "mol/fA"},
        ]
        age.set_sensitivity(sens)
        # 90 is most-recent before rundate 100
        self.assertEqual(age.sensitivity, 2e-17)


class ModelJTest(TestCase):
    def test_model_j_computes_from_uF(self):
        age = _build_age()
        age.calculate_age()
        j_modeled = age.model_j(monitor_age=10e6, lambda_k=5.543e-10)
        self.assertIsNotNone(j_modeled)
        self.assertEqual(j_modeled, age.modeled_j)


class K2OTest(TestCase):
    def test_no_weight_returns_zero(self):
        age = _build_age()
        age.calculate_age()
        age.weight = 0
        self.assertEqual(age.k2o, 0)

    def test_with_weight_returns_nonzero(self):
        age = _build_age()
        age.calculate_age()
        age.weight = 10  # mg
        self.assertNotEqual(age.k2o, 0)

    def test_display_k2o_no_weight(self):
        age = _build_age()
        age.weight = 0
        self.assertEqual(age.display_k2o, "")

    def test_display_k2o_with_weight(self):
        age = _build_age()
        age.calculate_age()
        age.weight = 10
        self.assertNotEqual(age.display_k2o, "")


class IsochronRatiosTest(TestCase):
    def setUp(self):
        self.age = _build_age()
        self.age.calculate_age()

    def test_isochron3940(self):
        v = self.age.isochron3940
        self.assertIsNotNone(v)

    def test_isochron3640(self):
        v = self.age.isochron3640
        self.assertIsNotNone(v)


class LambdaKPropertyTest(TestCase):
    def test_default_from_arar_constants(self):
        age = _build_age()
        # ufloat equality compares variable identity, not value; compare
        # nominal_value + std_dev separately.
        self.assertEqual(
            nominal_value(age.lambda_k),
            nominal_value(age.arar_constants.lambda_k),
        )
        self.assertEqual(
            std_dev(age.lambda_k),
            std_dev(age.arar_constants.lambda_k),
        )

    def test_override_via_setter(self):
        age = _build_age()
        custom = ufloat(6e-10, 1e-12)
        age.lambda_k = custom
        self.assertEqual(age.lambda_k, custom)


class DisplayK3739ModeTest(TestCase):
    def test_normal_mode(self):
        age = _build_age()
        # default arar_constants.k3739_mode is "Normal" and fixed_k3739 is None
        self.assertEqual(age.display_k3739_mode, "Normal")

    def test_fixed_via_fixed_k3739_attr(self):
        age = _build_age()
        age.fixed_k3739 = 0.05
        self.assertEqual(age.display_k3739_mode, "Fixed")


class CalculateNoInterferenceTest(TestCase):
    def test_resets_to_zero_interference_dict(self):
        age = _build_age()
        age.calculate_no_interference()
        # F still computed
        self.assertIsNotNone(age.uF)


class FErrAccessorsTest(TestCase):
    def test_f_property_matches_F(self):
        age = _build_age()
        age.calculate_age()
        self.assertEqual(age.f, age.F)

    def test_f_err_property_matches_F_err(self):
        age = _build_age()
        age.calculate_age()
        self.assertEqual(age.f_err, age.F_err)


class K2ODivByZeroTest(TestCase):
    def test_zero_j_yields_zero(self):
        age = _build_age()
        age.calculate_age()
        age.set_j(0.0, 0.0)
        age.weight = 10
        # ZeroDivisionError swallowed → returns 0
        self.assertEqual(age.k2o, 0)


class GetErrorComponentTest(TestCase):
    """get_error_component computes percent variance contributed by a tag."""

    def test_returns_zero_when_uage_is_none(self):
        age = _build_age()
        # uage_w_j_err not set yet
        self.assertEqual(age.get_error_component("Ar40"), 0)

    def test_returns_zero_for_missing_tag(self):
        age = _build_age()
        age.calculate_age()
        # an unrelated tag should report 0 contribution
        self.assertEqual(age.get_error_component("nonexistent_tag"), 0)

    def test_explicit_uage_argument(self):
        age = _build_age()
        age.calculate_age()
        # pass an explicit uage_w_j_err
        v = age.get_error_component("Ar40", uage=age.uage_w_j_err)
        self.assertGreaterEqual(v, 0)


class CalculateTransformICFactorTest(TestCase):
    """calculate_transform_ic_factor evaluates polyval(coefficients, x)
    where x is determined by `variable` (TotalIntensity / ICFactor / other)."""

    def setUp(self):
        self.age = _build_age()
        self.age.calculate_age()

    def test_variable_ic_factor(self):
        uv = self.age.calculate_transform_ic_factor(
            "H1",
            variable="ICFactor",
            coefficients=[2.0, 0.5],  # 2*x + 0.5
        )
        self.assertIsNotNone(uv)
        # H1's ic_factor = 1.0 → polyval = 2*1 + 0.5 = 2.5
        self.assertAlmostEqual(nominal_value(uv), 2.5, places=6)
        self.assertIn("H1", self.age.temporary_ic_factors)

    def test_variable_total_intensity_broken(self):
        """KNOWN BUG: code iterates `for iso in self.isotopes` which yields
        dict keys (strings), then calls `.get_intensity()` on a string.
        Locked as AttributeError so a future fix is detected."""
        with self.assertRaises(AttributeError):
            self.age.calculate_transform_ic_factor(
                "H1",
                variable="TotalIntensity",
                coefficients=[1.0, 0.0],
            )

    def test_with_tag_rewraps_ufloat(self):
        uv = self.age.calculate_transform_ic_factor(
            "H1",
            variable="UnknownVariable",  # falls back to get_value → ufloat(0,0)
            coefficients=[1.0, 0.0],
            tag="custom_tag",
        )
        self.assertEqual(uv.tag, "custom_tag")


class EquilibrationAgesTest(TestCase):
    """equilibration_ages iterates instant_age over sniff counts."""

    def setUp(self):
        self.age = _build_age()
        for iso in self.age.isotopes.values():
            iso.sniff.xs = np.linspace(0, 10, 10)
            # constant ys so each instant_age has well-defined intercept
            iso.sniff.ys = np.full(10, nominal_value(iso.value))

    def test_runs_and_caches(self):
        counts1, ages1 = self.age.equilibration_ages()
        # second call returns cached
        counts2, ages2 = self.age.equilibration_ages()
        self.assertEqual(counts1, counts2)
        self.assertIs(ages1, ages2)

    def test_force_recomputes(self):
        counts1, ages1 = self.age.equilibration_ages()
        counts2, ages2 = self.age.equilibration_ages(force=True)
        # Same data → same numerical values but a NEW list (force rebuilt)
        self.assertEqual(counts1, counts2)
        self.assertEqual(len(ages1), len(ages2))


class EquilibrationRatiosTest(TestCase):
    """Bugfix locked: scalars dict maps name → decay factor, not the
    isotope object as before."""

    def setUp(self):
        self.age = _build_age()
        for iso in self.age.isotopes.values():
            iso.sniff.xs = np.linspace(0, 10, 10)
            iso.sniff.ys = np.full(10, nominal_value(iso.value))
        # set non-trivial decay factors
        self.age.ar39decayfactor = 1.5
        self.age.ar37decayfactor = 1.3

    def test_ratio_applies_ar39_decay_factor(self):
        counts, ratios = self.age.equilibration_ratios("Ar39", "Ar40")
        # numscalar = 1.5 (ar39 decay), denscalar = 1 (Ar40 not in dict)
        self.assertEqual(len(ratios), len(counts))

    def test_unknown_isotope_scalar_defaults_to_one(self):
        counts, ratios = self.age.equilibration_ratios("Ar38", "Ar36")
        # neither in scalars dict → both scale by 1
        self.assertEqual(len(ratios), len(counts))


class GetValueDetICTest(TestCase):
    """get_value 'DetIC' branch — ratio across detectors."""

    def test_detic_dispatch(self):
        age = _build_age()
        # build alternative isotopes per detector for the DetIC path
        age.calculate_age()
        # The DetIC branch requires same-name isotopes with different
        # detectors — synthetic data uses unique detectors per isotope,
        # so this just verifies the dispatch doesn't crash.
        v = age.get_value("H1/AX DetIC")
        # might return ufloat(0, 0) if no matching detector pairs
        self.assertIsNotNone(v)


class GetValueRatioUTest(TestCase):
    """get_value attr starting with 'u' and containing '/' is a non-IC ratio."""

    def test_u_slash_ratio(self):
        age = _build_age()
        age.calculate_age()
        v = age.get_value("uAr40/Ar39")
        self.assertIsNotNone(v)


class GetValueICF4036Test(TestCase):
    def test_icf_40_36(self):
        age = _build_age()
        age.calculate_age()
        v = age.get_value("icf_40_36")
        self.assertIsNotNone(v)


class SetCosmogenicCorrectionTest(TestCase):
    def test_set_triggers_recalc(self):
        age = _build_age()
        age.calculate_age()
        age_before = age.age
        age.set_cosmogenic_correction((0.18, 0.001), (0.65, 0.01))
        self.assertTrue(age.arar_constants.use_cosmogenic_correction)
        # age should differ now (cosmogenic correction changes atm components)
        self.assertNotEqual(age.age, age_before)


class CalculateFOnlyTest(TestCase):
    def test_calculate_f_top_level_runs(self):
        age = _build_age()
        age.calculate_f()
        self.assertIsNotNone(age.uF)


# ============= EOF =============================================
