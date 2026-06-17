# ===============================================================================
# Copyright 2026 Jake Ross
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
import unittest

from pychron.options.monitor_constants import MonitorConstants
from pychron.pychron_constants import FLUX_CONSTANTS


class MonitorConstantsTestCase(unittest.TestCase):
    def setUp(self):
        self.key = list(FLUX_CONSTANTS.keys())[0]
        self.dc = FLUX_CONSTANTS[self.key]

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            MonitorConstants("not-a-real-monitor")

    def test_name_age_material(self):
        mc = MonitorConstants(self.key)
        self.assertEqual(mc.monitor_name, self.dc.get("monitor_name", ""))
        self.assertEqual(mc.monitor_age, self.dc.get("monitor_age", 0))
        self.assertEqual(mc.monitor_material, self.dc.get("monitor_material", ""))

    def test_lambda_k_is_sum_of_beta_and_ec(self):
        mc = MonitorConstants(self.key)
        lk = mc.lambda_k
        expected = self.dc["lambda_b"][0] + self.dc["lambda_ec"][0]
        self.assertAlmostEqual(lk.nominal_value, expected)

    def test_defaults_for_sparse_entry(self):
        # find a key missing optional fields, if any; otherwise this is a no-op
        for k, dc in FLUX_CONSTANTS.items():
            if "monitor_name" not in dc:
                mc = MonitorConstants(k)
                self.assertEqual(mc.monitor_name, "")
                break


class MonitorMixinDelegationTestCase(unittest.TestCase):
    def test_flux_options_properties_match_resolver(self):
        from pychron.options.flux import FluxOptions

        fo = FluxOptions()
        mc = MonitorConstants(fo.selected_monitor)
        self.assertEqual(fo.monitor_age, mc.monitor_age)
        self.assertEqual(fo.monitor_name, mc.monitor_name)
        self.assertEqual(fo.monitor_material, mc.monitor_material)
        self.assertEqual(fo.lambda_k.nominal_value, mc.lambda_k.nominal_value)


if __name__ == "__main__":
    unittest.main()
