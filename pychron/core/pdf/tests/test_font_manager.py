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
"""Cross-platform font registration regression tests.

These guard the behavior that makes PDF/screen fonts consistent across OSes:
bundled fonts register, missing faces collapse to a usable default, and
registration never raises (the old code crashed on a ``Vera.tff`` typo whenever
a primary face was unavailable). Only reportlab is required -- kiva/Qt are not
imported by the code paths under test.
"""

import unittest

from pychron.core.pdf import font_manager


class FontManagerTestCase(unittest.TestCase):
    def setUp(self):
        # exercise a clean registration each test
        font_manager._registered.clear()
        font_manager._loaded = False
        font_manager.load_pdf_fonts(force=True)

    def test_default_registered(self):
        """The default PDF font is always registered after loading."""
        self.assertIn(font_manager.DEFAULT_PDF_FONT, font_manager._registered)

    def test_bundled_fonts_registered(self):
        """Bundled families register under their canonical names."""
        for face in (
            "Arial",
            "Consolas",
            "DejaVu Sans",
            "DejaVu Serif",
            "DejaVu Sans Mono",
        ):
            self.assertIn(face, font_manager._registered)

    def test_every_offered_font_is_registered(self):
        """The cross-OS guarantee: every UI-offered family is registered.

        If TTF_FONTS and the bundled set drift apart, a user could pick a font
        that does not exist on other platforms -- exactly the bug this fix
        removes.
        """
        from pychron import pychron_constants

        for face in pychron_constants.TTF_FONTS:
            self.assertEqual(
                font_manager.resolve_pdf_fontname(face),
                face,
                msg="offered font %r is not registered/bundled" % face,
            )

    def test_helvetica_aliased_to_bundle(self):
        """Helvetica is backed by the bundled Arial so Greek glyphs render."""
        self.assertEqual(font_manager.resolve_pdf_fontname("Helvetica"), "Helvetica")
        self.assertIn("Helvetica", font_manager._registered)

    def test_legacy_faces_alias_to_bundled(self):
        """Removed families resolve to a registered bundled face."""
        for legacy in ("Andale Mono", "Cambria", "Verdana"):
            self.assertEqual(font_manager.resolve_pdf_fontname(legacy), legacy)
            self.assertIn(legacy, font_manager._registered)

    def test_missing_face_falls_back_to_default(self):
        """An unavailable face resolves to the default instead of vanishing."""
        self.assertEqual(
            font_manager.resolve_pdf_fontname("NoSuchFace"),
            font_manager.DEFAULT_PDF_FONT,
        )

    def test_empty_face_resolves_to_default(self):
        self.assertEqual(font_manager.resolve_pdf_fontname(""), font_manager.DEFAULT_PDF_FONT)
        self.assertEqual(font_manager.resolve_pdf_fontname(None), font_manager.DEFAULT_PDF_FONT)

    def test_load_is_idempotent(self):
        n = len(font_manager._registered)
        font_manager.load_pdf_fonts()
        self.assertEqual(len(font_manager._registered), n)

    def test_never_raises_without_bundled_fonts(self):
        """Missing bundled files must still yield a usable default, no crash."""
        original = font_manager.fonts_dir
        try:
            font_manager.fonts_dir = lambda: "/nonexistent/fonts"
            font_manager._registered.clear()
            font_manager._loaded = False
            font_manager.load_pdf_fonts(force=True)  # must not raise
            self.assertIn(font_manager.DEFAULT_PDF_FONT, font_manager._registered)
            self.assertEqual(
                font_manager.resolve_pdf_fontname("anything"),
                font_manager.DEFAULT_PDF_FONT,
            )
            # never raises even with no files/kiva available
            font_manager.register_application_fonts()
        finally:
            font_manager.fonts_dir = original


if __name__ == "__main__":
    unittest.main()
