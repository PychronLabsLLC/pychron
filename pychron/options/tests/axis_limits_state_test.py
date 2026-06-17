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

from pychron.options.axis_limits_state import AxisLimitsState, has_limits


class HasLimitsTestCase(unittest.TestCase):
    def test_none(self):
        self.assertFalse(has_limits(None))

    def test_equal_is_not_limits(self):
        self.assertFalse(has_limits((5, 5)))

    def test_distinct_is_limits(self):
        self.assertTrue(has_limits((0, 10)))


class AxisLimitsStateTestCase(unittest.TestCase):
    def test_starts_empty(self):
        s = AxisLimitsState()
        self.assertFalse(s.has())

    def test_capture_sets_limits_and_has(self):
        s = AxisLimitsState()
        s.capture((1, 9))
        self.assertEqual(s.limits, (1, 9))
        self.assertTrue(s.has())

    def test_capture_equal_bounds_is_not_has(self):
        s = AxisLimitsState()
        s.capture((4, 4))
        self.assertFalse(s.has())

    def test_reset_to_fixed(self):
        s = AxisLimitsState()
        s.capture((1, 9))
        s.reset((2, 8))
        self.assertEqual(s.limits, (2, 8))
        self.assertTrue(s.has())

    def test_reset_default_clears(self):
        s = AxisLimitsState()
        s.capture((1, 9))
        s.reset()
        self.assertEqual(s.limits, (0, 0))
        self.assertFalse(s.has())

    def test_explicit_flag_forces_has(self):
        s = AxisLimitsState()
        s.limits = (3, 3)
        s.explicit = True
        self.assertTrue(s.has())

    def test_instances_are_independent(self):
        a = AxisLimitsState()
        b = AxisLimitsState()
        a.capture((1, 2))
        self.assertFalse(b.has())


if __name__ == "__main__":
    unittest.main()
