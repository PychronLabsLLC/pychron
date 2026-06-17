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
View-limit state for a single plot axis.

Extracted from AuxPlot as a composed value object. AuxPlot used to inline the
captured-view limits as parallel transient traits (``xlimits`` + ``_has_xlimits``
and the ``ylimits`` pair). Bundling each axis's view state here makes the unit
explicit, independently testable, and gives the rebuild path a clear
capture / reset vocabulary so a figure rebuild can preserve the user's current
pan/zoom instead of silently dropping it.
"""
from traits.api import HasTraits, Bool, Tuple, Float


def has_limits(lims):
    return lims is not None and lims[0] != lims[1]


class AxisLimitsState(HasTraits):
    # the captured view limits (lo, hi). Transient: a view, never serialized.
    limits = Tuple(Float, Float, transient=True)
    # explicitly flagged as set even if lo == hi
    explicit = Bool(False, transient=True)

    def capture(self, lims):
        """Record the current view limits (e.g. after a user pan/zoom)."""
        self.limits = tuple(lims)
        self.explicit = has_limits(lims)

    def reset(self, fixed=(0.0, 0.0)):
        """Drop the captured view, falling back to the given fixed limits."""
        self.limits = tuple(fixed)
        self.explicit = has_limits(fixed)

    def has(self):
        """True if a usable view/fixed limit is present."""
        return self.explicit or has_limits(self.limits)


# ============= EOF =============================================
