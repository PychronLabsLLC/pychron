# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# ===============================================================================
"""
Coverage for ArArConstants — unit scaling, serialization, cosmogenic.
"""

from unittest import TestCase

from uncertainties import nominal_value, std_dev, ufloat

from pychron.processing.arar_constants import ArArConstants


class ScaleAgeTest(TestCase):
    def setUp(self):
        self.ac = ArArConstants()

    def test_a_to_a_identity(self):
        self.assertEqual(self.ac.scale_age(1e6, current="a", target="a"), 1e6)

    def test_a_to_ma(self):
        self.assertAlmostEqual(self.ac.scale_age(10e6, current="a", target="Ma"), 10.0, places=6)

    def test_ma_to_a(self):
        self.assertAlmostEqual(self.ac.scale_age(10.0, current="Ma", target="a"), 10e6, places=6)

    def test_a_to_ka(self):
        self.assertAlmostEqual(self.ac.scale_age(5000.0, current="a", target="ka"), 5.0, places=6)

    def test_ka_to_a(self):
        self.assertAlmostEqual(self.ac.scale_age(5.0, current="ka", target="a"), 5000.0, places=6)

    def test_a_to_ga(self):
        self.assertAlmostEqual(self.ac.scale_age(2e9, current="a", target="Ga"), 2.0, places=6)

    def test_ga_to_a(self):
        self.assertAlmostEqual(self.ac.scale_age(2.0, current="Ga", target="a"), 2e9, places=6)

    def test_round_trip_a_ma_a(self):
        v = self.ac.scale_age(7e6, current="a", target="Ma")
        v2 = self.ac.scale_age(v, current="Ma", target="a")
        self.assertAlmostEqual(v2, 7e6, places=6)


class ToDictTest(TestCase):
    def test_to_dict_has_expected_keys(self):
        ac = ArArConstants()
        d = ac.to_dict()
        for k in (
            "fixed_k3739",
            "atm4036",
            "atm4038",
            "lambda_Cl36",
            "lambda_Ar37",
            "lambda_Ar39",
            "lambda_k",
        ):
            self.assertIn(k, d)
            self.assertIn("{}_err".format(k), d)
        self.assertIn("abundance_sensitivity", d)

    def test_to_dict_values_are_floats(self):
        ac = ArArConstants()
        d = ac.to_dict()
        for v in d.values():
            self.assertIsInstance(v, (int, float))

    def test_to_dict_atm4036_matches_property(self):
        ac = ArArConstants()
        d = ac.to_dict()
        self.assertAlmostEqual(d["atm4036"], nominal_value(ac.atm4036), places=10)


class CosmoDictTest(TestCase):
    def setUp(self):
        self.ac = ArArConstants()
        self.ac.set_cosmogenic_ratios((0.18, 0.001), (0.65, 0.01))

    def test_cosmo_to_dict_has_keys(self):
        d = self.ac.cosmo_to_dict()
        self.assertIn("use_cosmogenic_correction", d)
        self.assertIn("cosmo3836", d)
        self.assertIn("cosmo3836_err", d)
        self.assertIn("solar3836", d)
        self.assertIn("solar3836_err", d)

    def test_cosmo_to_dict_values(self):
        d = self.ac.cosmo_to_dict()
        self.assertAlmostEqual(d["solar3836"], 0.18, places=6)
        self.assertAlmostEqual(d["solar3836_err"], 0.001, places=6)
        self.assertAlmostEqual(d["cosmo3836"], 0.65, places=6)
        self.assertAlmostEqual(d["cosmo3836_err"], 0.01, places=6)
        self.assertTrue(d["use_cosmogenic_correction"])

    def test_cosmo_from_dict_round_trip(self):
        ac2 = ArArConstants()
        d = self.ac.cosmo_to_dict()
        ac2.cosmo_from_dict(d)
        self.assertAlmostEqual(nominal_value(ac2.solar3836), 0.18, places=6)
        self.assertAlmostEqual(std_dev(ac2.solar3836), 0.001, places=6)
        self.assertTrue(ac2.use_cosmogenic_correction)

    def test_cosmo_from_dict_defaults_to_zero(self):
        ac = ArArConstants()
        ac.cosmo_from_dict({})
        self.assertEqual(nominal_value(ac.solar3836), 0)
        self.assertEqual(nominal_value(ac.cosmo3836), 0)
        self.assertFalse(ac.use_cosmogenic_correction)


class Atm3836PropertiesTest(TestCase):
    def setUp(self):
        self.ac = ArArConstants()

    def test_atm3836_v_returns_nominal(self):
        self.assertEqual(self.ac.atm3836_v, nominal_value(self.ac.atm3836))

    def test_atm3836_e_returns_std_dev(self):
        self.assertEqual(self.ac.atm3836_e, std_dev(self.ac.atm3836))

    def test_atm3836_is_atm4036_over_atm4038(self):
        expected = nominal_value(self.ac.atm4036) / nominal_value(self.ac.atm4038)
        self.assertAlmostEqual(nominal_value(self.ac.atm3836), expected, places=10)


class UFloatGettersTest(TestCase):
    """All `_get_*` methods return ufloats wrapping `_v` + `_e` attrs."""

    def setUp(self):
        self.ac = ArArConstants()

    def test_lambda_Cl36(self):
        self.assertIsNotNone(self.ac.lambda_Cl36)

    def test_lambda_Ar37(self):
        self.assertIsNotNone(self.ac.lambda_Ar37)

    def test_lambda_Ar39(self):
        self.assertIsNotNone(self.ac.lambda_Ar39)

    def test_lambda_b(self):
        self.assertIsNotNone(self.ac.lambda_b)

    def test_lambda_e(self):
        self.assertIsNotNone(self.ac.lambda_e)

    def test_lambda_k_default_is_lambda_b_plus_e(self):
        expected_nom = nominal_value(self.ac.lambda_b) + nominal_value(self.ac.lambda_e)
        self.assertAlmostEqual(nominal_value(self.ac.lambda_k), expected_nom, places=15)

    def test_lambda_k_can_be_overridden(self):
        custom = ufloat(7e-10, 1e-12)
        self.ac.lambda_k = custom
        self.assertEqual(nominal_value(self.ac.lambda_k), 7e-10)

    def test_atm4036_uses_trapped_if_set(self):
        trapped = ufloat(300.0, 1.0)
        self.ac.trapped_atm4036 = trapped
        self.assertEqual(self.ac.atm4036, trapped)

    def test_fixed_k3739(self):
        v = self.ac.fixed_k3739
        self.assertIsNotNone(v)


class SetCosmogenicRatiosTest(TestCase):
    def test_set_cosmogenic_ratios(self):
        ac = ArArConstants()
        self.assertFalse(ac.use_cosmogenic_correction)
        ac.set_cosmogenic_ratios((0.2, 0.005), (0.7, 0.02))
        self.assertTrue(ac.use_cosmogenic_correction)
        self.assertAlmostEqual(ac.solar3836_v, 0.2, places=6)
        self.assertAlmostEqual(ac.solar3836_e, 0.005, places=6)
        self.assertAlmostEqual(ac.cosmo3836_v, 0.7, places=6)
        self.assertAlmostEqual(ac.cosmo3836_e, 0.02, places=6)


# ============= EOF =============================================
