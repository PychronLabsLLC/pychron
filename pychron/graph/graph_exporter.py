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
Image/PDF export for a Graph.

Extracted from Graph as a composed collaborator: rendering a plot container to
an image file is a self-contained responsibility that does not need to live in
the Graph base class. A Graph holds a GraphExporter and delegates to it, rather
than inheriting the rendering methods.
"""
import os

from traits.api import HasTraits

from pychron.core.helpers.filetools import add_extension

IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".gif"]
DEFAULT_IMAGE_EXT = IMAGE_EXTENSIONS[0]


def get_file_path(action="save as", **kw):
    from pyface.api import FileDialog, OK

    dlg = FileDialog(action=action, **kw)
    if dlg.open() == OK:
        return dlg.path


class GraphExporter(HasTraits):
    def save(self, graph, type_="pic", path=None):
        if path is None:
            path = get_file_path(default_directory=os.path.expanduser("~"))

        if path is not None:
            if type_ == "pdf" or path.endswith(".pdf"):
                self.render_to_pdf(graph, filename=path)
            else:
                # auto add an extension to the filename if not present
                # extension is necessary for PIL compression
                # set default save type_ DEFAULT_IMAGE_EXT='.png'
                for ei in IMAGE_EXTENSIONS:
                    if path.endswith(ei):
                        self.render_to_pic(graph, path)
                        break
                else:
                    path = add_extension(path, DEFAULT_IMAGE_EXT)
                    self.render_to_pic(graph, path)

    def render_to_pdf(self, graph, save=True, canvas=None, filename=None, dest_box=None):
        # NOTE: PDF rendering is currently a no-op (implementation disabled).
        pass

    def render_to_pic(self, graph, filename):
        from chaco.plot_graphics_context import PlotGraphicsContext

        p = graph.plotcontainer
        gc = PlotGraphicsContext((int(p.outer_width), int(p.outer_height)))
        gc.render_component(p)
        gc.save(filename)


# ============= EOF =============================================
