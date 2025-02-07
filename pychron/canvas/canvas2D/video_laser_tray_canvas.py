# ===============================================================================
# Copyright 2011 Jake Ross
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

# ============= enthought library imports =======================
# ============= standard library imports ========================
# ============= local library imports  ==========================
from __future__ import absolute_import
from .laser_tray_canvas import LaserTrayCanvas
from pychron.canvas.canvas2D.video_canvas import VideoCanvas


class VideoLaserTrayCanvas(LaserTrayCanvas, VideoCanvas):
    """ """

    bgcolor = "lightgray"

    def set_stage_position(self, x, y):
        """ """

        super(VideoLaserTrayCanvas, self).set_stage_position(x, y)
        self.adjust_limits("x", x)
        self.adjust_limits("y", y)

    def clear_desired_position(self):
        self._desired_position = None
        self.request_redraw()

    def get_screen_center(self):
        lp = self.index_mapper.low_pos
        hp = self.index_mapper.high_pos
        cx = (hp - lp) / 2.0 + lp

        lp = self.value_mapper.low_pos
        hp = self.value_mapper.high_pos
        cy = (hp - lp) / 2.0 + lp
        return cx, cy

    def get_center_rect_position(self, w=0, h=0):
        lp = self.index_mapper.low_pos
        hp = self.index_mapper.high_pos
        cw = hp - lp

        cx = (cw - w) / 2.0 + lp

        lp = self.value_mapper.low_pos
        hp = self.value_mapper.high_pos
        ch = hp - lp
        cy = (ch - h) / 2.0 + lp
        return cx, cy

    def add_markup_circle(self, x, y, r, **kw):
        from pychron.canvas.canvas2D.scene.primitives.primitives import Circle

        r = Circle(x=x, y=y, radius=r, space="screen", fill=False, **kw)
        self.scene.add_item(r)

    def add_markup_rect(self, x, y, w, h, **kw):
        from pychron.canvas.canvas2D.scene.primitives.primitives import Rectangle

        r = Rectangle(x=x, y=y, width=w, height=h, space="screen", fill=False, **kw)
        self.scene.add_item(r)

    def _calc_relative_move_direction(self, char, direction):
        """
        correct for sense of camera
        """
        if char in ("Left", "Right"):
            di = -1 if self.video.hflip else 1
        else:
            di = -1 if self.video.vflip else 1
        return direction * di


# ============= EOF ====================================
