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

from pychron.graph.limits_manager import LimitsManager


class _FakeRange:
    def __init__(self, low=0.0, high=1.0):
        self.low = low
        self.high = high


class _FakeData:
    def __init__(self, data=None):
        self._data = data or {}

    def list_data(self):
        return list(self._data.keys())

    def get_data(self, k):
        return self._data[k]


class _FakePlot:
    def __init__(self, scale="linear", low=0.0, high=1.0, data=None):
        self.index_range = _FakeRange(low, high)
        self.value_range = _FakeRange(low, high)
        self.index_scale = scale
        self.value_scale = scale
        self.data = _FakeData(data)


class LimitsManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.lm = LimitsManager()

    def test_get_returns_low_high(self):
        plot = _FakePlot(low=2.0, high=8.0)
        self.assertEqual(self.lm.get(plot, "index"), (2.0, 8.0))

    def test_set_absolute(self):
        plot = _FakePlot()
        change = self.lm.set(plot, 0.0, 10.0, "index", 0)
        self.assertTrue(change)
        self.assertEqual((plot.index_range.low, plot.index_range.high), (0.0, 10.0))

    def test_set_no_change_returns_false(self):
        plot = _FakePlot(low=0.0, high=10.0)
        change = self.lm.set(plot, 0.0, 10.0, "index", 0)
        self.assertFalse(change)

    def test_percentage_pad_expands_range(self):
        plot = _FakePlot()
        self.lm.set(plot, 0.0, 100.0, "value", "0.1")
        self.assertEqual((plot.value_range.low, plot.value_range.high), (-10.0, 110.0))

    def test_pair_pad(self):
        plot = _FakePlot()
        self.lm.set(plot, 0.0, 10.0, "index", "0.1,0.2")
        self.assertEqual((plot.index_range.low, plot.index_range.high), (-1.0, 12.0))

    def test_equal_min_max_uses_pad(self):
        plot = _FakePlot()
        change = self.lm.set(plot, 5.0, 5.0, "index", 2)
        # mi == ma branch sets high/low around the value but reports no change
        self.assertFalse(change)
        self.assertEqual((plot.index_range.low, plot.index_range.high), (3.0, 7.0))

    def test_log_scale_snaps_to_powers_of_ten(self):
        plot = _FakePlot(scale="log")
        self.lm.set(plot, 3.0, 300.0, "value", 0)
        self.assertEqual((plot.value_range.low, plot.value_range.high), (1.0, 1000.0))


if __name__ == "__main__":
    unittest.main()
