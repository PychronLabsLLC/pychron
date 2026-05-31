# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Coverage for IsotopeGroup — the dict-like container backing every
ArArAge / Analysis. Tests dict ops, isotope dispatch by name/detector,
ratio computation, append_data signal-kind dispatch, and the
__getattr__ ratio shortcut.
"""

from unittest import TestCase

import numpy as np
from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.isotope import Baseline, Isotope
from pychron.processing.isotope_group import IsotopeGroup


def _build_iso(name, detector, intercept=100.0, n=50):
    iso = Isotope(name, detector)
    iso.xs = np.linspace(0, 100, n)
    iso.ys = intercept + 0.0 * iso.xs
    iso.fit = "linear"
    iso.error_type = "SEM"
    iso.set_baseline(0.0, 0.0)
    iso.set_blank(0.0, 0.0)
    return iso


def _build_group(**intensities):
    intensities = intensities or {
        "Ar40": ("H1", 1000.0),
        "Ar39": ("AX", 100.0),
        "Ar38": ("L1", 10.0),
        "Ar37": ("L2", 5.0),
        "Ar36": ("CDD", 2.0),
    }
    g = IsotopeGroup()
    for name, (det, intercept) in intensities.items():
        g.isotopes[name] = _build_iso(name, det, intercept)
    return g


class DictLikeAPITest(TestCase):
    def setUp(self):
        self.g = _build_group()

    def test_keys(self):
        self.assertEqual(set(self.g.keys()), {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_getitem(self):
        self.assertEqual(self.g["Ar40"].name, "Ar40")

    def test_values_returns_isotopes(self):
        names = {v.name for v in self.g.values()}
        self.assertEqual(names, {"Ar40", "Ar39", "Ar38", "Ar37", "Ar36"})

    def test_items(self):
        items = self.g.items()
        self.assertEqual(len(items), 5)
        for k, v in items:
            self.assertEqual(v.name, k)

    def test_iteritems_returns_iterator(self):
        result = dict(self.g.iteritems())
        self.assertEqual(set(result.keys()), set(self.g.keys()))

    def test_itervalues(self):
        names = {v.name for v in self.g.itervalues()}
        self.assertEqual(len(names), 5)

    def test_pop(self):
        removed = self.g.pop("Ar36")
        self.assertEqual(removed.name, "Ar36")
        self.assertNotIn("Ar36", self.g.keys())

    def test_sorted_values(self):
        """sort_isotopes orders Ar40, Ar39, Ar38, Ar37, Ar36."""
        ordered = [v.name for v in self.g.sorted_values()]
        self.assertEqual(ordered, ["Ar40", "Ar39", "Ar38", "Ar37", "Ar36"])

    def test_sorted_values_reversed(self):
        ordered = [v.name for v in self.g.sorted_values(reverse=True)]
        self.assertEqual(ordered, ["Ar36", "Ar37", "Ar38", "Ar39", "Ar40"])


class IterIsotopesTest(TestCase):
    def test_iter_isotopes_in_sort_order(self):
        g = _build_group()
        names = [i.name for i in g.iter_isotopes()]
        self.assertEqual(names, ["Ar40", "Ar39", "Ar38", "Ar37", "Ar36"])

    def test_clear_isotopes_replaces_with_blanks(self):
        g = _build_group()
        g.clear_isotopes()
        # all replaced with new Isotope() — original xs/ys gone
        for v in g.values():
            self.assertEqual(v.xs.shape[0], 0)


class BaselineAccessorsTest(TestCase):
    def setUp(self):
        self.g = _build_group()
        self.g["Ar40"].set_baseline(5.0, 0.1)

    def test_get_baseline_strips_bs_suffix(self):
        bl = self.g.get_baseline("Ar40bs")
        self.assertEqual(bl._value, 5.0)

    def test_get_baseline_missing_returns_empty(self):
        """Regression: previously raised TypeError because Baseline() lacks
        required (name, detector) args. Now returns a placeholder Baseline."""
        bl = self.g.get_baseline("Xe129")
        self.assertIsInstance(bl, Baseline)
        # value defaults to 0 — caller can subtract without crashing
        self.assertEqual(bl._value, 0)

    def test_get_baseline_value_by_name(self):
        v = self.g.get_baseline_value("Ar40")
        self.assertAlmostEqual(nominal_value(v), 5.0, places=6)

    def test_get_baseline_value_by_detector(self):
        v = self.g.get_baseline_value("H1")
        self.assertAlmostEqual(nominal_value(v), 5.0, places=6)

    def test_get_baseline_corrected_default_on_missing(self):
        v = self.g.get_baseline_corrected_value("Xe129", default=42)
        self.assertEqual(nominal_value(v), 42)

    def test_get_baseline_corrected_present(self):
        v = self.g.get_baseline_corrected_value("Ar40")
        # synthetic intercept = 1000, baseline = 5 → 995
        self.assertAlmostEqual(nominal_value(v), 995.0, places=2)


class GetIntensityTest(TestCase):
    def setUp(self):
        self.g = _build_group()

    def test_get_intensity_by_name(self):
        v = self.g.get_intensity("Ar40")
        self.assertAlmostEqual(nominal_value(v), 1000.0, places=2)

    def test_get_intensity_missing(self):
        v = self.g.get_intensity("Xe129")
        self.assertEqual(nominal_value(v), 0)

    def test_get_non_ic_corrected(self):
        v = self.g.get_non_ic_corrected("Ar40")
        self.assertAlmostEqual(nominal_value(v), 1000.0, places=2)

    def test_get_non_ic_corrected_missing(self):
        v = self.g.get_non_ic_corrected("Xe129")
        self.assertEqual(nominal_value(v), 0)


class GetRatioTest(TestCase):
    def setUp(self):
        self.g = _build_group()

    def test_ratio_slash(self):
        # Ar40 / Ar39 = 1000/100 = 10
        v = self.g.get_ratio("Ar40/Ar39")
        self.assertAlmostEqual(nominal_value(v), 10.0, places=2)

    def test_ratio_underscore(self):
        v = self.g.get_ratio("Ar40_Ar39")
        self.assertAlmostEqual(nominal_value(v), 10.0, places=2)

    def test_ratio_non_ic_corr(self):
        v = self.g.get_ratio("Ar40/Ar39", non_ic_corr=True)
        self.assertAlmostEqual(nominal_value(v), 10.0, places=2)

    def test_ratio_missing_isotope_returns_none(self):
        v = self.g.get_ratio("Ar40/Xe129")
        self.assertIsNone(v)


class GetSlopeTest(TestCase):
    def test_get_slope_by_name(self):
        g = _build_group()
        # Synthetic data has 0 slope → 0.0
        self.assertAlmostEqual(g.get_slope("Ar40"), 0.0, places=8)

    def test_get_slope_by_detector(self):
        g = _build_group()
        self.assertAlmostEqual(g.get_slope("H1"), 0.0, places=8)

    def test_get_slope_unknown_returns_zero(self):
        g = _build_group()
        self.assertEqual(g.get_slope("UNKNOWN_DETECTOR"), 0)


class GetValuesTest(TestCase):
    def test_get_values_all(self):
        g = _build_group()
        vs = g.get_values("Ar40", -1)
        self.assertEqual(len(vs), 50)

    def test_get_values_last_n(self):
        g = _build_group()
        vs = g.get_values("Ar40", 5)
        self.assertEqual(len(vs), 5)

    def test_get_values_missing_returns_none(self):
        g = _build_group()
        self.assertIsNone(g.get_values("Xe129", 5))


class GetCurrentIntensityTest(TestCase):
    def test_returns_last_ys(self):
        g = _build_group()
        v = g.get_current_intensity("Ar40")
        self.assertAlmostEqual(v, g["Ar40"].ys[-1], places=6)

    def test_missing_returns_none(self):
        g = _build_group()
        self.assertIsNone(g.get_current_intensity("Xe129"))


class HasAttrTest(TestCase):
    """has_attr references self.computed; only meaningful on ArArAge
    subclasses. Test via a minimal subclass that defines computed."""

    def setUp(self):
        class _AgeLike(IsotopeGroup):
            computed = {}

        self.g = _AgeLike()
        for name, det in [("Ar40", "H1"), ("Ar39", "AX")]:
            self.g.isotopes[name] = _build_iso(name, det)

    def test_isotope_present(self):
        self.assertTrue(self.g.has_attr("Ar40"))

    def test_computed_present(self):
        self.g.computed["k39"] = ufloat(1.0, 0)
        self.assertTrue(self.g.has_attr("k39"))

    def test_isotope_absent(self):
        self.assertFalse(bool(self.g.has_attr("Xe129")))


class GetIsotopeTest(TestCase):
    def setUp(self):
        self.g = _build_group()

    def test_by_name(self):
        iso = self.g.get_isotope(name="Ar40")
        self.assertEqual(iso.name, "Ar40")

    def test_by_detector(self):
        iso = self.g.get_isotope(detector="H1")
        self.assertEqual(iso.name, "Ar40")

    def test_colon_in_name(self):
        iso = self.g.get_isotope(name="Ar40:H1")
        self.assertEqual(iso.name, "Ar40")
        self.assertEqual(iso.detector, "H1")

    def test_colon_in_detector(self):
        iso = self.g.get_isotope(detector="Ar40:H1")
        self.assertEqual(iso.name, "Ar40")

    def test_name_required(self):
        with self.assertRaises(NotImplementedError):
            self.g.get_isotope()

    def test_name_with_wrong_detector_returns_none(self):
        result = self.g.get_isotope(name="Ar40", detector="WrongDet")
        self.assertIsNone(result)

    def test_kind_sniff(self):
        iso = self.g.get_isotope(name="Ar40", kind="sniff")
        self.assertEqual(iso.name, "Ar40")  # sniff inherits name
        # sniff is a Sniff instance
        from pychron.processing.isotope import Sniff

        self.assertIsInstance(iso, Sniff)

    def test_kind_baseline(self):
        iso = self.g.get_isotope(name="Ar40", kind="baseline")
        self.assertIsInstance(iso, Baseline)


class GetIsotopeTitleTest(TestCase):
    def test_matching_detector(self):
        g = _build_group()
        self.assertEqual(g.get_isotope_title("Ar40", "H1"), "Ar40")

    def test_mismatched_detector(self):
        g = _build_group()
        self.assertEqual(g.get_isotope_title("Ar40", "L2"), "Ar40L2")


class DetectorsAndPairsTest(TestCase):
    def test_detectors_list(self):
        g = _build_group()
        self.assertEqual(set(g.detectors()), {"H1", "AX", "L1", "L2", "CDD"})

    def test_pairs_structure(self):
        g = _build_group()
        pairs = g.pairs()
        self.assertEqual(len(pairs), 5)
        for key, name, det in pairs:
            self.assertEqual(key, name)


class GetIsotopesForDetectorTest(TestCase):
    def test_yields_matching_isotopes(self):
        g = _build_group()
        result = list(g.get_isotopes_for_detector("H1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Ar40")

    def test_empty_for_unknown_detector(self):
        g = _build_group()
        result = list(g.get_isotopes_for_detector("nonexistent"))
        self.assertEqual(result, [])


class SetIsotopeTest(TestCase):
    def test_set_existing_isotope(self):
        g = _build_group()
        iso = g.set_isotope("Ar40", "H1", (500.0, 1.0))
        self.assertEqual(iso._value, 500.0)
        self.assertEqual(iso._error, 1.0)

    def test_set_new_isotope_creates_it(self):
        g = _build_group()
        iso = g.set_isotope("Xe129", "L3", (50.0, 0.5))
        self.assertIn("Xe129", g.isotopes)
        self.assertEqual(iso.detector, "L3")

    def test_set_isotope_with_kwargs(self):
        g = _build_group()
        g.set_isotope("Ar40", "H1", (500.0, 1.0), correct_for_blank=False)
        self.assertFalse(g["Ar40"].correct_for_blank)


class SetBaselineBlankTest(TestCase):
    def test_set_baseline(self):
        g = _build_group()
        g.set_baseline("Ar40", "H1", (3.0, 0.3))
        self.assertEqual(g["Ar40"].baseline._value, 3.0)

    def test_set_blank(self):
        g = _build_group()
        g.set_blank("Ar40", "H1", (2.0, 0.2))
        self.assertEqual(g["Ar40"].blank._value, 2.0)

    def test_clear_baselines(self):
        g = _build_group()
        g["Ar40"].set_baseline(5.0, 0.1)
        g.clear_baselines()
        self.assertEqual(g["Ar40"].baseline._value, 0)

    def test_clear_blanks(self):
        g = _build_group()
        g["Ar40"].set_blank(2.0, 0.1)
        g.clear_blanks()
        self.assertEqual(g["Ar40"].blank._value, 0)

    def test_clear_error_components(self):
        g = _build_group()
        for iso in g.itervalues():
            iso.age_error_component = 42.0
        g.clear_error_components()
        for iso in g.itervalues():
            self.assertEqual(iso.age_error_component, 0)


class AppendDataTest(TestCase):
    def setUp(self):
        self.g = _build_group()

    def test_append_signal_to_existing(self):
        before = self.g["Ar40"].xs.shape[0]
        ok = self.g.append_data("Ar40", "H1", 110.0, 1005.0, kind="signal")
        self.assertTrue(ok)
        self.assertEqual(self.g["Ar40"].xs.shape[0], before + 1)

    def test_append_baseline_matches_by_detector(self):
        ok = self.g.append_data("Ar40", "H1", 110.0, 5.0, kind="baseline")
        self.assertTrue(ok)
        # baseline xs grew
        self.assertEqual(self.g["Ar40"].baseline.xs.shape[0], 1)

    def test_append_sniff(self):
        ok = self.g.append_data("Ar40", "H1", 110.0, 999.0, kind="sniff")
        self.assertTrue(ok)
        self.assertEqual(self.g["Ar40"].sniff.xs.shape[0], 1)
        self.assertEqual(self.g["Ar40"]._value, 999.0)


class StoredValueStateTest(TestCase):
    def test_set_state_propagates(self):
        g = _build_group()
        g.set_stored_value_states(True)
        for i in g.iter_isotopes():
            self.assertTrue(i.use_stored_value)
            self.assertTrue(i.baseline.use_stored_value)

    def test_save_captures_current_state(self):
        g = _build_group()
        # set all True
        g.set_stored_value_states(True, save=False)
        # explicit save
        g.save_stored_value_state()
        # now flip to False via direct attribute
        for i in g.iter_isotopes():
            i.use_stored_value = False
            i.baseline.use_stored_value = False
        # revert restores the saved True state
        g.revert_use_stored_values()
        for i in g.iter_isotopes():
            self.assertTrue(i.use_stored_value)
            self.assertTrue(i.baseline.use_stored_value)

    def test_revert_no_op_when_nothing_saved(self):
        g = _build_group()
        # _sv is None; revert should be a no-op
        g.revert_use_stored_values()
        for i in g.iter_isotopes():
            self.assertFalse(i.use_stored_value)


class GetattrRatioTest(TestCase):
    """__getattr__ treats `Ar40/Ar39` style attribute access as a ratio."""

    def test_ratio_via_getattr(self):
        g = _build_group()
        # IsotopeGroup.__getattr__ calls self.get_value(n) / self.get_value(d).
        # IsotopeGroup itself has no get_value, but ArArAge subclasses do.
        # Verify the method raises AttributeError when no get_value.
        with self.assertRaises(AttributeError):
            _ = g.Ar40

    def test_unknown_attr_raises(self):
        g = _build_group()
        with self.assertRaises(AttributeError):
            _ = g.completely_unknown_thing


class LoggingTest(TestCase):
    """The debug/info/warning/critical methods should not raise."""

    def test_log_methods(self):
        g = _build_group()
        g.name = "test"
        g.debug("a")
        g.info("b")
        g.warning("c")
        g.critical("d")


class GetICFactorTest(TestCase):
    """get_ic_factor reads from detectors.cfg or detectors.yaml under
    paths.spectrometer_dir. Tests use a tmp dir patched onto paths."""

    def setUp(self):
        import tempfile
        from pychron.paths import paths

        self.tmpdir = tempfile.mkdtemp()
        self._old_dir = paths.spectrometer_dir
        paths.spectrometer_dir = self.tmpdir
        self.g = _build_group()
        self.g.name = "test"

    def tearDown(self):
        import shutil
        from pychron.paths import paths

        paths.spectrometer_dir = self._old_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_files_returns_default(self):
        """No cfg/yaml → returns ic_factor=1 ± 0."""
        ic = self.g.get_ic_factor("H1")
        self.assertEqual(nominal_value(ic), 1.0)
        self.assertEqual(std_dev(ic), 0.0)

    def test_yaml_known_detector(self):
        import os

        yaml_path = os.path.join(self.tmpdir, "detectors.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "- name: H1\n  ic_factor: 1.02\n  ic_factor_err: 0.01\n"
                "- name: AX\n  ic_factor: 0.98\n  ic_factor_err: 0.02\n"
            )

        ic_h1 = self.g.get_ic_factor("H1")
        self.assertAlmostEqual(nominal_value(ic_h1), 1.02, places=6)
        self.assertAlmostEqual(std_dev(ic_h1), 0.01, places=6)

        ic_ax = self.g.get_ic_factor("AX")
        self.assertAlmostEqual(nominal_value(ic_ax), 0.98, places=6)
        self.assertAlmostEqual(std_dev(ic_ax), 0.02, places=6)

    def test_yaml_unknown_detector_returns_default(self):
        import os

        yaml_path = os.path.join(self.tmpdir, "detectors.yaml")
        with open(yaml_path, "w") as f:
            f.write("- name: H1\n  ic_factor: 1.02\n  ic_factor_err: 0.01\n")

        ic = self.g.get_ic_factor("nonexistent_detector")
        # falls through to default 1±0
        self.assertEqual(nominal_value(ic), 1.0)
        self.assertEqual(std_dev(ic), 0.0)

    def test_yaml_case_insensitive(self):
        """streq is casefold; "h1" should match "H1"."""
        import os

        yaml_path = os.path.join(self.tmpdir, "detectors.yaml")
        with open(yaml_path, "w") as f:
            f.write("- name: H1\n  ic_factor: 1.05\n  ic_factor_err: 0.005\n")

        ic = self.g.get_ic_factor("h1")
        self.assertAlmostEqual(nominal_value(ic), 1.05, places=6)

    def test_yaml_missing_err_defaults_to_zero(self):
        import os

        yaml_path = os.path.join(self.tmpdir, "detectors.yaml")
        with open(yaml_path, "w") as f:
            f.write("- name: H1\n  ic_factor: 1.03\n")

        ic = self.g.get_ic_factor("H1")
        self.assertAlmostEqual(nominal_value(ic), 1.03, places=6)
        self.assertEqual(std_dev(ic), 0.0)

    def test_cfg_takes_precedence_over_yaml(self):
        """detectors.cfg is checked first; if present, yaml is ignored."""
        import os

        cfg_path = os.path.join(self.tmpdir, "detectors.cfg")
        with open(cfg_path, "w") as f:
            f.write("[H1]\nic_factor = 1.10\nic_factor_err = 0.05\n")

        yaml_path = os.path.join(self.tmpdir, "detectors.yaml")
        with open(yaml_path, "w") as f:
            f.write("- name: H1\n  ic_factor: 99.0\n  ic_factor_err: 9.0\n")

        ic = self.g.get_ic_factor("H1")
        # cfg value, not yaml
        self.assertAlmostEqual(nominal_value(ic), 1.10, places=6)
        self.assertAlmostEqual(std_dev(ic), 0.05, places=6)

    def test_cfg_missing_options_default(self):
        """ic_factor option missing in cfg section → defaults to 1±0."""
        import os

        cfg_path = os.path.join(self.tmpdir, "detectors.cfg")
        with open(cfg_path, "w") as f:
            f.write("[H1]\n")  # section exists but no ic_factor

        ic = self.g.get_ic_factor("H1")
        self.assertEqual(nominal_value(ic), 1.0)
        self.assertEqual(std_dev(ic), 0.0)


# ============= EOF =============================================
