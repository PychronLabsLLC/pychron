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

from pychron.graph.series_manager import PlotSeriesGenerators, name_generator


class NameGeneratorTestCase(unittest.TestCase):
    def test_increments_with_base(self):
        g = name_generator("x")
        self.assertEqual([next(g) for _ in range(3)], ["x0", "x1", "x2"])


class PlotSeriesGeneratorsTestCase(unittest.TestCase):
    def test_data_names_increment_independently(self):
        g = PlotSeriesGenerators()
        self.assertEqual((g.next_x(), g.next_y(), g.next_yer()), ("x0", "y0", "yer0"))
        self.assertEqual((g.next_x(), g.next_y(), g.next_yer()), ("x1", "y1", "yer1"))

    def test_two_instances_do_not_share_state(self):
        a = PlotSeriesGenerators()
        b = PlotSeriesGenerators()
        a.next_x()
        a.next_x()
        # b is independent -> starts at x0
        self.assertEqual(b.next_x(), "x0")

    def test_next_color_advances(self):
        g = PlotSeriesGenerators()
        c1 = g.next_color()
        c2 = g.next_color()
        self.assertNotEqual(c1, c2)

    def test_next_color_excludes_scalar(self):
        g = PlotSeriesGenerators()
        first = PlotSeriesGenerators().next_color()
        # excluding the first color should skip it
        self.assertNotEqual(g.next_color(exclude=first), first)

    def test_next_color_excludes_list(self):
        g = PlotSeriesGenerators()
        probe = PlotSeriesGenerators()
        excluded = [probe.next_color(), probe.next_color()]
        self.assertNotIn(g.next_color(exclude=excluded), excluded)


if __name__ == "__main__":
    unittest.main()
