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
Characterization tests for the Graph class hierarchy.

These pin the observable behavior of the core graph classes so the planned
composition-over-inheritance refactor of the hierarchy can proceed safely.
They are intentionally behavioral (new_plot / new_series / record / fit) rather
than structural, so they survive a change in the inheritance graph.
"""
import os
import tempfile
import unittest

from numpy import array_equal

from pychron.graph.graph import Graph
from pychron.graph.graph_exporter import GraphExporter
from pychron.graph.stacked_graph import StackedGraph, ColumnStackedGraph
from pychron.graph.stream_graph import StreamGraph, StreamStackedGraph
from pychron.graph.regression_graph import RegressionGraph
from pychron.graph.stacked_regression_graph import (
    StackedRegressionGraph,
    ColumnStackedRegressionGraph,
)
from pychron.graph.time_series_graph import (
    TimeSeriesGraph,
    TimeSeriesStackedGraph,
    TimeSeriesStreamGraph,
    TimeSeriesStreamStackedGraph,
)


class GraphTestCase(unittest.TestCase):
    def test_new_plot_appends(self):
        g = Graph()
        self.assertEqual(len(g.plots), 0)
        g.new_plot()
        g.new_plot()
        self.assertEqual(len(g.plots), 2)

    def test_new_series_stores_data(self):
        g = Graph()
        g.new_plot()
        g.new_series([1, 2, 3], [4, 5, 6])

        self.assertEqual(g.series, [[("x0", "y0")]])
        self.assertTrue(array_equal(g.get_data(plotid=0, axis=0), [1, 2, 3]))
        self.assertTrue(array_equal(g.get_data(plotid=0, axis=1), [4, 5, 6]))

    def test_new_series_returns_pair(self):
        g = Graph()
        g.new_plot()
        ret = g.new_series([1, 2, 3], [4, 5, 6])
        self.assertEqual(len(ret), 2)


class GraphExporterTestCase(unittest.TestCase):
    """Image/pdf export is a composed collaborator, not inherited behavior."""

    def test_graph_composes_an_exporter(self):
        g = Graph()
        self.assertIsInstance(g._exporter, GraphExporter)

    def test_save_writes_png(self):
        g = Graph()
        g.new_plot()
        g.new_series([1, 2, 3], [4, 5, 6])

        path = os.path.join(tempfile.mkdtemp(), "out.png")
        g.save(path)

        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 0)


class SeriesGenerationTestCase(unittest.TestCase):
    """Per-plot series naming + color generation (composed PlotSeriesGenerators)."""

    def test_series_names_are_per_plot(self):
        g = Graph()
        g.new_plot()
        g.new_plot()
        g.new_series([1, 2, 3], [4, 5, 6], plotid=0)
        g.new_series([1, 2, 3], [7, 8, 9], plotid=0)
        g.new_series([1, 2, 3], [1, 1, 1], plotid=1)

        # each plot numbers its own series from 0
        self.assertEqual(g.series[0], [("x0", "y0"), ("x1", "y1")])
        self.assertEqual(g.series[1], [("x0", "y0")])

    def test_get_next_color_advances_per_plot(self):
        g = Graph()
        g.new_plot()
        c1 = g.get_next_color(plotid=0)
        c2 = g.get_next_color(plotid=0)
        self.assertNotEqual(c1, c2)

    def test_get_next_color_excludes(self):
        g = Graph()
        g.new_plot()
        c1 = g.get_next_color(plotid=0)
        self.assertNotEqual(g.get_next_color(exclude=c1, plotid=0), c1)


class LimitsTestCase(unittest.TestCase):
    """Graph delegates limit get/set to the composed LimitsManager."""

    def _graph(self):
        g = Graph()
        g.new_plot()
        g.new_series([0, 1, 2, 3, 4], [10, 20, 30, 40, 50])
        return g

    def test_set_get_x_limits(self):
        g = self._graph()
        g.set_x_limits(0, 4)
        self.assertEqual(g.get_x_limits(), (0.0, 4.0))

    def test_set_get_y_limits(self):
        g = self._graph()
        g.set_y_limits(0, 50)
        self.assertEqual(g.get_y_limits(), (0.0, 50.0))

    def test_percentage_pad(self):
        g = self._graph()
        g.set_y_limits(0, 100, pad="0.1")
        self.assertEqual(g.get_y_limits(), (-10.0, 110.0))


class StackedGraphTestCase(unittest.TestCase):
    def test_stacks_multiple_plots(self):
        g = StackedGraph()
        g.new_plot()
        g.new_plot()
        g.new_plot()
        self.assertEqual(len(g.plots), 3)

    def test_new_series_returns_pair(self):
        g = StackedGraph()
        g.new_plot()
        ret = g.new_series([1, 2, 3], [1, 2, 3], plotid=0)
        self.assertEqual(len(ret), 2)


class StreamGraphTestCase(unittest.TestCase):
    def _stream(self):
        g = StreamGraph()
        g.new_plot(scan_width=5)
        g.new_series(type="scatter")
        return g

    def test_record_appends_single_point(self):
        g = self._stream()
        xn, yn = g.series[0][0]
        plot = g.plots[0]
        self.assertEqual(len(plot.data.get_data(yn)), 0)

        g.record(5.0)
        g.record(6.0)

        self.assertTrue(array_equal(plot.data.get_data(yn), [5.0, 6.0]))

    def test_record_multiple_series(self):
        g = StreamGraph()
        g.new_plot(scan_width=5)
        g.new_series(type="scatter")
        g.new_series(type="line", plotid=0)

        g.record_multiple([1.0, 2.0])

        for series in range(2):
            xn, yn = g.series[0][series]
            self.assertEqual(len(g.plots[0].data.get_data(yn)), 1)


class RegressionGraphTestCase(unittest.TestCase):
    def test_fit_attaches_regressor(self):
        g = RegressionGraph()
        g.new_plot()
        plot, scatter, line = g.new_series([1, 2, 3, 4], [2, 4, 6, 8], fit="linear")
        self.assertTrue(hasattr(line, "regressor"))

    def test_new_series_returns_triple_with_fit(self):
        g = RegressionGraph()
        g.new_plot()
        ret = g.new_series([1, 2, 3, 4], [2, 4, 6, 8], fit="linear")
        self.assertEqual(len(ret), 3)


class CombinationGraphTestCase(unittest.TestCase):
    """
    The combination classes mix two orthogonal feature axes via multiple
    inheritance. Pin that each one is-a both parents and can build a plot, so a
    refactor that replaces the inheritance with composition can be verified
    against the same observable behavior.
    """

    def test_time_series_stacked_is_both(self):
        g = TimeSeriesStackedGraph()
        self.assertIsInstance(g, TimeSeriesGraph)
        self.assertIsInstance(g, StackedGraph)
        g.new_plot()
        g.new_plot()
        self.assertEqual(len(g.plots), 2)

    def test_time_series_stream_is_both(self):
        g = TimeSeriesStreamGraph()
        self.assertIsInstance(g, TimeSeriesGraph)
        self.assertIsInstance(g, StreamGraph)

    def test_time_series_stream_stacked_is_all(self):
        g = TimeSeriesStreamStackedGraph()
        self.assertIsInstance(g, TimeSeriesGraph)
        self.assertIsInstance(g, StreamStackedGraph)

    def test_stream_stacked_is_both(self):
        g = StreamStackedGraph()
        self.assertIsInstance(g, StreamGraph)
        self.assertIsInstance(g, StackedGraph)

    def test_stacked_regression_is_both(self):
        g = StackedRegressionGraph()
        self.assertIsInstance(g, RegressionGraph)
        self.assertIsInstance(g, StackedGraph)

    def test_stacked_regression_new_series_binds(self):
        g = StackedRegressionGraph(bind_index=False)
        g.new_plot()
        ret = g.new_series([1, 2, 3, 4], [2, 4, 6, 8], fit="linear", plotid=0)
        # StackedRegressionGraph.new_series returns the underlying triple/pair
        self.assertIn(len(ret), (2, 3))

    def test_column_stacked_regression_is_both(self):
        g = ColumnStackedRegressionGraph()
        self.assertIsInstance(g, RegressionGraph)
        self.assertIsInstance(g, ColumnStackedGraph)


if __name__ == "__main__":
    unittest.main()
