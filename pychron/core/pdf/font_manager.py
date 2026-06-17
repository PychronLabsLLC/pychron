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
Centralized, cross-platform font registration for pychron.

Fonts have rendered inconsistently across operating systems because pychron
historically relied on system-installed fonts resolved through kiva's
``findfont()``.  Many of the selectable families (Calibri, Cambria, Consolas,
...) exist only on Windows, so a figure built on one OS rendered with arbitrary
substitute fonts -- or failed to export to PDF entirely -- on another.  The old
import-time registration loop in ``save_pdf_dialog`` also crashed outright
whenever a primary face was missing, because its ``Vera.tff`` fallback was a
typo that raised an uncaught ``TTFError`` (the correct name is ``Vera.ttf``).

This module makes font handling deterministic:

* Fonts bundled in ``resources/fonts`` are the authoritative source.  They are
  registered with reportlab (PDF export) and, via kiva, with the GUI toolkit
  and kiva's AGG/image backends (on-screen + PNG export).  The *same* font file
  is therefore used for screen, image, and PDF on every OS.
* Registration never raises.  A missing or unreadable font is logged and
  skipped; it can never crash app startup or PDF export.
* :func:`resolve_pdf_fontname` maps any requested face to a font name that is
  guaranteed to be registered with reportlab, falling back to the bundled
  default (Arial, which has full Greek/maths glyph coverage for pychron's
  lambda/sigma/Delta/plus-minus usage).
"""

import logging
import os

from reportlab import rl_config
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger("fonts")

# Bundled font file -> (canonical face name, additional aliases it answers to).
# The canonical names are exactly the families offered in the UI
# (pychron_constants.TTF_FONTS) so the user can only pick fonts that ship with
# pychron and therefore render identically on macOS, Linux, and Windows.
# Aliases let a figure authored with a non-bundled or platform-default face
# (e.g. "Helvetica", "Times New Roman", "Courier", legacy "modern"/"Vera") fall
# through to the nearest bundled file instead of an arbitrary system substitute.
_BUNDLED_FONTS = {
    "arial.ttf": ("Arial", ("arial", "Helvetica", "helvetica", "modern")),
    "Consolas.ttf": ("Consolas", ("consolas",)),
    "DejaVuSans.ttf": (
        "DejaVu Sans",
        ("dejavu sans", "DejaVuSans", "Vera", "Bitstream Vera Sans", "Verdana"),
    ),
    "DejaVuSerif.ttf": (
        "DejaVu Serif",
        (
            "dejavu serif",
            "DejaVuSerif",
            "Times",
            "Times New Roman",
            "Georgia",
            "Cambria",
            "serif",
        ),
    ),
    "DejaVuSansMono.ttf": (
        "DejaVu Sans Mono",
        (
            "dejavu sans mono",
            "DejaVuSansMono",
            "Courier",
            "Courier New",
            "Monaco",
            "Andale Mono",
            "monospace",
        ),
    ),
}

# The face every unresolved request collapses to.  Backed by the bundled
# arial.ttf, which covers the Greek/maths glyphs pychron renders.
DEFAULT_PDF_FONT = "Arial"

# reportlab font names successfully registered this process.
_registered: set = set()
_loaded = False


def fonts_dir():
    """Absolute path to the bundled fonts directory.

    Resolved from :mod:`pychron.paths` when available, else relative to this
    file so the module remains importable/testable without the full app.
    """
    try:
        from pychron.paths import fonts as _fonts

        return _fonts
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
        return os.path.join(root, "resources", "fonts")


def _register(name, filename, subfont_index=0):
    """Register ``filename`` with reportlab under ``name``. Never raises."""
    if name in _registered:
        return True
    try:
        pdfmetrics.registerFont(TTFont(name, filename, subfontIndex=subfont_index))
        _registered.add(name)
        return True
    except Exception as e:
        logger.debug("could not register font %s from %s: %s", name, filename, e)
        return False


def _register_bundled():
    """Register every bundled font under its canonical name and aliases."""
    fd = fonts_dir()
    for filename, (canonical, aliases) in _BUNDLED_FONTS.items():
        path = os.path.join(fd, filename)
        if not os.path.isfile(path):
            logger.warning("bundled font missing: %s", path)
            continue
        # register once per name so the same file backs the canonical face and
        # all of its aliases (and case variants).
        for name in (canonical, canonical.lower(), *aliases):
            _register(name, path)


def _register_system():
    """Best-effort registration of the remaining selectable families.

    Uses kiva's font lookup to locate whatever the host OS provides.  Anything
    that cannot be found or registered is silently skipped -- it will resolve to
    the bundled default at draw time instead.
    """
    try:
        from kiva.api import Font, NORMAL
        from pychron import pychron_constants
    except Exception as e:
        logger.debug("skipping system font registration: %s", e)
        return

    for face in pychron_constants.TTF_FONTS:
        for name in (face, face.lower()):
            if name in _registered:
                continue
            try:
                spec = Font(face_name=name, style=NORMAL, weight=NORMAL).findfont()
            except Exception as e:
                logger.debug("findfont failed for %s: %s", name, e)
                continue

            if isinstance(spec, str):
                _register(name, spec)
            else:
                _register(name, spec.filename, getattr(spec, "face_index", 0))


def load_pdf_fonts(force=False):
    """Register all fonts used for PDF export. Idempotent and never raises.

    Bundled fonts win; system fonts fill in the rest on a best-effort basis.
    Guarantees :data:`DEFAULT_PDF_FONT` is registered so
    :func:`resolve_pdf_fontname` always returns a usable name.
    """
    global _loaded
    if _loaded and not force:
        return

    # let reportlab find the bundled files by bare name too.
    fd = fonts_dir()
    if fd not in rl_config.TTFSearchPath:
        rl_config.TTFSearchPath.append(fd)

    _register_bundled()
    _register_system()

    # absolute last resort: reportlab always ships Vera.ttf, so the default
    # name is never left dangling even if the bundled arial.ttf is absent.
    if DEFAULT_PDF_FONT not in _registered:
        if not _register(DEFAULT_PDF_FONT, "Vera.ttf"):
            logger.error("no usable default PDF font could be registered")

    _loaded = True


def resolve_pdf_fontname(face):
    """Return a reportlab font name guaranteed to be registered.

    ``face`` is a requested family (e.g. ``"Calibri"``); if it -- or its
    lower-case form -- was registered it is returned as-is, otherwise the
    bundled default is used so text never silently disappears.
    """
    load_pdf_fonts()
    if not face:
        return DEFAULT_PDF_FONT
    for name in (face, face.lower()):
        if name in _registered:
            return name
    return DEFAULT_PDF_FONT


def register_application_fonts():
    """Make the bundled fonts available to the GUI toolkit and kiva backends.

    Call once after the Qt application exists so on-screen and PNG rendering use
    the same files as PDF export.  Never raises.
    """
    fd = fonts_dir()
    paths = [os.path.join(fd, fn) for fn in _BUNDLED_FONTS if os.path.isfile(os.path.join(fd, fn))]
    if not paths:
        logger.warning("no bundled fonts to register with the application")
        return
    try:
        from kiva.fonttools.app_font import add_application_fonts

        add_application_fonts(paths)
        logger.info("registered %d bundled application font(s)", len(paths))
    except Exception as e:
        logger.warning("could not register application fonts: %s", e)


# ============= EOF =============================================
