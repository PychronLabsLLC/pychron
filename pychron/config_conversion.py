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
"""Convert legacy ``.cfg`` (ConfigParser/INI) configuration files to YAML.

YAML is the preferred configuration format for devices and other
``ConfigMixin`` consumers. Legacy ``.cfg`` files are converted on the fly the
first time they are loaded (see ``ConfigMixin.get_configuration``); the
original ``.cfg`` file is left in place so the conversion is non-destructive.

This module can also be run as a script to batch-convert a file or directory:

    python -m pychron.config_conversion <path-to-cfg-or-directory>
"""

# ============= standard library imports ========================
import os
from configparser import ConfigParser, Error as ConfigParserError
from typing import Dict, List, Optional, Tuple, Union

import yaml

# ============= local library imports  ==========================

_TRUE_VALUES = ("true", "yes", "on")
_FALSE_VALUES = ("false", "no", "off")

ValueType = Union[bool, int, float, str]


def parse_value(value: str) -> ValueType:
    """Best-effort typed conversion of an INI string value.

    Booleans (true/false/yes/no/on/off), ints, and floats are converted;
    everything else stays a string. Values whose integer form would lose
    information (e.g. leading zeros like "01") stay strings.
    """
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    low = stripped.lower()
    if low in _TRUE_VALUES:
        return True
    if low in _FALSE_VALUES:
        return False

    try:
        i = int(stripped)
    except ValueError:
        pass
    else:
        return i if str(i) == stripped else stripped

    try:
        return float(stripped)
    except ValueError:
        return stripped


def cfg_to_dict(path: str) -> Dict[str, Dict[str, ValueType]]:
    """Parse a ``.cfg`` file into a nested ``{section: {option: value}}`` dict."""
    parser = ConfigParser()
    with open(path, "r") as rfile:
        parser.read_file(rfile)

    return {
        section: {option: parse_value(v) for option, v in parser.items(section)}
        for section in parser.sections()
    }


def yaml_sibling_path(path: str) -> str:
    """Return ``<path-without-extension>.yaml``."""
    root, _ = os.path.splitext(path)
    return "{}.yaml".format(root)


def convert_cfg_to_yaml(
    path: str, output: Optional[str] = None, overwrite: bool = False
) -> Optional[str]:
    """Convert a ``.cfg`` file to YAML.

    Returns the path to the YAML file, or None if conversion failed. If the
    destination already exists and ``overwrite`` is False, the existing YAML
    file wins and is returned untouched. The source ``.cfg`` is never modified.
    """
    if output is None:
        output = yaml_sibling_path(path)

    if os.path.isfile(output) and not overwrite:
        return output

    try:
        obj = cfg_to_dict(path)
    except (ConfigParserError, OSError, UnicodeDecodeError):
        return None

    try:
        with open(output, "w") as wfile:
            yaml.dump(obj, wfile, default_flow_style=False, sort_keys=False)
    except OSError:
        return None

    return output


def convert_directory(
    root: str, recursive: bool = True, overwrite: bool = False
) -> List[Tuple[str, Optional[str]]]:
    """Batch-convert every ``.cfg`` file under ``root``.

    Returns a list of ``(cfg_path, yaml_path_or_None)`` tuples.
    """
    results: List[Tuple[str, Optional[str]]] = []
    if recursive:
        walker = os.walk(root)
    else:
        walker = [(root, [], os.listdir(root))]

    for dirpath, _dirnames, filenames in walker:
        for filename in sorted(filenames):
            if filename.endswith(".cfg"):
                cfg_path = os.path.join(dirpath, filename)
                results.append((cfg_path, convert_cfg_to_yaml(cfg_path, overwrite=overwrite)))
    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Convert .cfg configuration files to YAML")
    ap.add_argument("path", help="a .cfg file or a directory to scan")
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing .yaml files")
    ap.add_argument("--no-recursive", action="store_true", help="do not recurse into directories")
    args = ap.parse_args()

    if os.path.isdir(args.path):
        converted = convert_directory(
            args.path, recursive=not args.no_recursive, overwrite=args.overwrite
        )
    else:
        converted = [(args.path, convert_cfg_to_yaml(args.path, overwrite=args.overwrite))]

    for src, dst in converted:
        print("{} -> {}".format(src, dst if dst else "FAILED"))

# ============= EOF =============================================
