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
Per-plot series identity generation.

Extracted from Graph as a composed value object. Graph previously kept four
parallel ``List`` traits (x/y/yer data-name generators and a color generator),
all indexed by plotid and appended in lockstep at three different call sites --
a classic "keep N lists in sync" smell. Bundling them into one object per plot
makes the unit explicit and impossible to desynchronize.
"""
from pychron.core.helpers.color_generators import colorname_generator as color_generator


def name_generator(base):
    i = 0
    while 1:
        yield base + str(i)
        i += 1


class PlotSeriesGenerators:
    """Generates the x/y/yer data names and series colors for a single plot."""

    def __init__(self):
        self._x = name_generator("x")
        self._y = name_generator("y")
        self._yer = name_generator("yer")
        self._color = color_generator()

    def next_x(self):
        return next(self._x)

    def next_y(self):
        return next(self._y)

    def next_yer(self):
        return next(self._yer)

    def next_color(self, exclude=None):
        nc = next(self._color)
        if exclude is not None:
            if not isinstance(exclude, (list, tuple)):
                exclude = [exclude]
            while nc in exclude:
                nc = next(self._color)
        return nc


# ============= EOF =============================================
