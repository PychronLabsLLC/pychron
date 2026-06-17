# ===============================================================================
# Copyright 2012 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
from pychron.graph.regression_graph import RegressionGraph
from pychron.graph.stacked_graph import StackedGraph, ColumnStackedGraph


class StackedRegressionGraph(RegressionGraph, StackedGraph):
    def new_series(self, *args, **kw):
        ret = super(StackedRegressionGraph, self).new_series(*args, **kw)
        if len(ret) == 3:
            plot, scatter, line = ret
        else:
            scatter, plot = ret

        if self.bind_index:
            bind_id = kw.get("bind_id")
            if bind_id:
                self._bind_index(scatter, bind_id)
        return ret


class ColumnStackedRegressionGraph(RegressionGraph, ColumnStackedGraph):
    pass


# ============= EOF =============================================
