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
Regression test: a figure rebuild must NOT reset the user's axis limits.

Previously FigureContainer.refresh(clear=True) called clear_ylimits/clear_xlimits
on every aux_plot, so any rebuild (e.g. an options change) discarded the user's
current pan/zoom. The view limits are now only reset on a genuine data change
(FigureEditor.set_items), so refresh must leave captured limits intact.
"""
import unittest

from pychron.options.aux_plot import AuxPlot
from pychron.pipeline.plot.figure_container import FigureContainer


class _FakeComponent:
    def __init__(self):
        self.components = []
        self.redrawn = False

    def add(self, g):
        self.components.append(g)

    def invalidate_and_redraw(self):
        self.redrawn = True


class _FakePlotOptions:
    def __init__(self, aux_plots):
        self.aux_plots = aux_plots


class _FakePanel:
    def __init__(self, aux_plots):
        self.plot_options = _FakePlotOptions(aux_plots)
        self.graphs = 0

    def make_graph(self, row, col):
        self.graphs += 1
        return object()


class _FakeModel:
    def __init__(self, panel):
        self._panel = panel
        self._served = False

    def reset_panel_gen(self):
        self._served = False

    def next_panel(self):
        if self._served:
            raise StopIteration
        self._served = True
        return self._panel


class FigureContainerLimitsTestCase(unittest.TestCase):
    def setUp(self):
        self.ap = AuxPlot()
        self.ap.capture_limits(xlims=(10, 20), ylims=(1, 9))
        self.panel = _FakePanel([self.ap])
        self.container = FigureContainer()
        # set without notification: avoid the _model_changed handler, which
        # would need a fully-formed plot_options/layout. We exercise refresh()
        # directly.
        self.container.trait_setq(
            model=_FakeModel(self.panel),
            component=_FakeComponent(),
            rows=1,
            cols=1,
        )

    def test_rebuild_preserves_view_limits(self):
        self.container.refresh(clear=True)

        # the graph was rebuilt ...
        self.assertEqual(self.panel.graphs, 1)
        self.assertTrue(self.container.component.redrawn)
        # ... but the user's captured limits survived
        self.assertEqual(self.ap.xlimits, (10, 20))
        self.assertEqual(self.ap.ylimits, (1, 9))
        self.assertTrue(self.ap.has_xlimits())
        self.assertTrue(self.ap.has_ylimits())


if __name__ == "__main__":
    unittest.main()
