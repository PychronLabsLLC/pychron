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
Axis-limit application for a Graph.

Extracted from Graph as a composed collaborator. Interpreting the ``pad``
argument (absolute, percentage string, or ``"lo,hi"`` pair), the log-scale
clamping, and the change detection are a self-contained algorithm that operates
on a chaco plot's data range. The collaborator never redraws -- it returns
whether the range changed and lets the Graph own the redraw.
"""
import logging
import math

from numpy import inf

logger = logging.getLogger(__name__)


class LimitsManager:
    def get(self, plot, axis):
        try:
            ra = getattr(plot, "%s_range" % axis)
            return ra.low, ra.high
        except AttributeError as e:
            logger.debug("get_limits failed error=%s", e)

    def set(self, plot, mi, ma, axis, pad, pad_style="symmetric"):
        """
        Apply min/max (with padding) to ``plot``'s ``axis`` data range.

        Returns True if the range changed (the caller is responsible for any
        redraw), False otherwise.
        """
        ra = getattr(plot, "{}_range".format(axis))
        scale = getattr(plot, "{}_scale".format(axis))

        if isinstance(pad, str):
            # interpret pad as a percentage of the range
            # ie '0.1' => 0.1*(ma-mi)
            if ma is None:
                ma = ra.high
            if mi is None:
                mi = ra.low

            if mi == -inf:
                mi = 0
            if ma == inf:
                ma = 100

            if ma is not None and mi is not None:
                dev = ma - mi

                def convert(p):
                    p = float(p) * dev
                    if abs(p) < 1e-10:
                        p = 1
                    return p

                if "," in pad:
                    pad = [convert(p) for p in pad.split(",")]
                else:
                    pad = convert(pad)
            if not pad:
                pad = 0

            try:
                if isinstance(pad, list):
                    mi -= pad[0]
                elif pad_style in ("symmetric", "lower"):
                    mi -= pad
            except TypeError:
                pass

            try:
                if isinstance(pad, list):
                    ma += pad[1]
                elif pad_style in ("symmetric", "upper"):
                    ma += pad
            except TypeError:
                pass

        if scale == "log":
            try:
                if mi <= 0:
                    mi = inf
                    data = plot.data
                    for di in data.list_data():
                        if "y" in di:
                            ya = sorted(data.get_data(di))

                            i = 0
                            try:
                                while ya[i] <= 0:
                                    i += 1
                                if ya[i] < mi:
                                    mi = ya[i]

                            except IndexError:
                                mi = 0.01

                mi = 10 ** math.floor(math.log(mi, 10))

                ma = 10 ** math.ceil(math.log(ma, 10))
            except ValueError:
                return False

        change = False
        if mi == ma:
            if not pad:
                pad = 1

            ra.high = ma + pad
            ra.low = ma - pad
        else:
            if mi is not None:
                change = ra.low != mi
                if isinstance(mi, (int, float)):
                    if mi < ra.high or (ma is not None and mi < ma):
                        ra.low = mi
                else:
                    ra.low = mi

            if ma is not None:
                change = change or ra.high != ma
                if isinstance(ma, (int, float)):
                    if ma > ra.low or (mi is not None and ma > mi):
                        ra.high = ma
                else:
                    ra.high = ma

        return change


# ============= EOF =============================================
