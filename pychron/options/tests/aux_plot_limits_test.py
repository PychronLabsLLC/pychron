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
"""
AuxPlot now composes two AxisLimitsState objects. These pin the backward-
compatible surface (xlimits / ylimits / _has_xlimits / _has_ylimits and the
has_* / clear_* methods) plus the new capture_limits API, and the asymmetric
clear semantics (clear_ylimits keeps ymin/ymax; clear_xlimits zeroes xmin/xmax).
"""
import unittest

from pychron.options.aux_plot import AuxPlot


class AuxPlotLimitsTestCase(unittest.TestCase):
    def test_starts_without_limits(self):
        a = AuxPlot()
        self.assertFalse(a.has_xlimits())
        self.assertFalse(a.has_ylimits())

    def test_xlimits_property_roundtrip(self):
        a = AuxPlot()
        a.xlimits = (10, 20)
        self.assertEqual(a.xlimits, (10, 20))
        self.assertTrue(a.has_xlimits())

    def test_has_flag_property_roundtrip(self):
        a = AuxPlot()
        a._has_xlimits = True
        self.assertTrue(a.has_xlimits())

    def test_capture_limits(self):
        a = AuxPlot()
        a.capture_limits(xlims=(1, 2), ylims=(3, 4))
        self.assertEqual(a.xlimits, (1, 2))
        self.assertEqual(a.ylimits, (3, 4))
        self.assertTrue(a.has_xlimits())
        self.assertTrue(a.has_ylimits())

    def test_clear_ylimits_resets_to_fixed_and_keeps_ymin_ymax(self):
        a = AuxPlot()
        a.ymin, a.ymax = 5, 50
        a.capture_limits(ylims=(11, 22))
        a.clear_ylimits()
        self.assertEqual(a.ylimits, (5, 50))
        self.assertEqual((a.ymin, a.ymax), (5, 50))

    def test_clear_xlimits_zeroes_fixed_bounds(self):
        a = AuxPlot()
        a.xmin, a.xmax = 5, 50
        a.capture_limits(xlims=(11, 22))
        a.clear_xlimits()
        self.assertEqual(a.xlimits, (0, 0))
        self.assertEqual((a.xmin, a.xmax), (0, 0))
        self.assertFalse(a.has_xlimits())

    def test_instances_do_not_share_state(self):
        a = AuxPlot()
        b = AuxPlot()
        a.capture_limits(xlims=(1, 2))
        self.assertFalse(b.has_xlimits())

    def test_view_limits_excluded_from_to_dict(self):
        a = AuxPlot()
        a.capture_limits(xlims=(1, 2), ylims=(3, 4))
        d = a.to_dict()
        self.assertNotIn("xlimits", d)
        self.assertNotIn("ylimits", d)


if __name__ == "__main__":
    unittest.main()
