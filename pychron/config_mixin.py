# ===============================================================================
# Copyright 2016 Jake Ross
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

# ============= enthought library imports =======================
# ============= standard library imports ========================
import os
from configparser import ConfigParser
from typing import Any, List, Optional, Tuple

import yaml

# ============= local library imports  ==========================
from pychron.config_conversion import convert_cfg_to_yaml
from pychron.core.helpers.strtools import to_bool
from pychron.core.yaml import yload
from pychron.paths import paths


class YAMLParser:
    """ConfigParser-compatible facade over a YAML mapping.

    YAML is the preferred configuration format. This adapter lets code written
    against the ConfigParser API (has_section/has_option/get/set/write/...)
    consume and produce YAML files transparently.
    """

    def __init__(self, obj: Optional[dict] = None):
        self._obj = obj if isinstance(obj, dict) else {}

    # reading
    def sections(self) -> List[str]:
        return list(self._obj.keys())

    def has_section(self, section: str) -> bool:
        return section in self._obj

    def has_option(self, section: str, option: str) -> bool:
        sec = self._obj.get(section)
        return isinstance(sec, dict) and option in sec

    def options(self, section: str) -> List[str]:
        sec = self._obj.get(section)
        return list(sec.keys()) if isinstance(sec, dict) else []

    def items(self, section: str) -> List[Tuple[str, Any]]:
        sec = self._obj.get(section)
        return list(sec.items()) if isinstance(sec, dict) else []

    def get(self, section: str, option: str) -> Any:
        sec = self._obj.get(section)
        if isinstance(sec, dict):
            return sec.get(option)

    def getfloat(self, section: str, option: str) -> Optional[float]:
        v = self.get(section, option)
        if v is not None:
            return float(v)

    def getint(self, section: str, option: str) -> Optional[int]:
        v = self.get(section, option)
        if v is not None:
            return int(v)

    def getboolean(self, section: str, option: str) -> Optional[bool]:
        v = self.get(section, option)
        if v is not None:
            return to_bool(v)

    # writing
    def add_section(self, section: str) -> None:
        self._obj.setdefault(section, {})

    def remove_section(self, section: str) -> None:
        self._obj.pop(section, None)

    def set(self, section: str, option: str, value: Any) -> None:
        self._obj.setdefault(section, {})[option] = value

    def write(self, fp) -> None:
        yaml.dump(self._obj, fp, default_flow_style=False, sort_keys=False)


class ParserWrapper:
    """Lazily wraps either a ConfigParser (.cfg) or a YAMLParser (.yaml/.yml)."""

    _parser = None

    def add_section(self, name):
        if self._parser is None:
            self._parser = ConfigParser()
        self._parser.add_section(name)

    def set(self, *args, **kw):
        if self._parser is None:
            self._parser = ConfigParser()
        self._parser.set(*args, **kw)

    def read(self, path):
        if path.endswith(".cfg"):
            p = ConfigParser()
            p.read(path)
        else:
            with open(path, "r") as rfile:
                p = YAMLParser(yload(rfile))

        self._parser = p

    def __getattr__(self, item):
        return getattr(self._parser, item)


class ConfigMixin:
    configuration_dir_name = None
    configuration_dir_path = None
    configuration_name = None
    config_path = None

    def configparser_factory(self):
        return ParserWrapper()

    def config_get_options(self, config, section):
        r = []
        if config.has_section(section):
            r = config.options(section)
        return r

    def config_get(self, config, section, option, cast=None, optional=False, default=None):
        if cast is not None:
            func = getattr(config, "get{}".format(cast))
        else:
            func = config.get

        if not config.has_option(section, option):
            if not optional:
                if self.logger is not None:
                    self.warning("Need to specifiy {}:{}".format(section, option))

            return default
        else:
            return func(section, option)

    def set_attribute(self, config, attribute, section, option, **kw):
        r = self.config_get(config, section, option, **kw)
        if r is not None:
            setattr(self, attribute, r)

    def write_configuration(self, config, path=None):
        if path is None:
            path = self.config_path

        with open(path, "w") as f:
            config.write(f)

    def get_configuration(self, path=None, name=None, warn=True, set_path=True, auto_convert=True):
        """Locate and read this object's configuration file.

        Resolution order when no explicit path is given: ``<name>.yaml``,
        ``<name>.yml``, ``<name>.cfg``. YAML is the preferred format; when a
        legacy ``.cfg`` file is found it is converted to a sibling ``.yaml``
        file on the fly (the original is left in place) and the YAML file is
        loaded instead. Pass ``auto_convert=False`` to read a ``.cfg``
        directly.
        """
        if path is None:
            path = self.config_path
            if path is None:
                device_dir = paths.device_dir

                if self.configuration_dir_name:
                    base = os.path.join(device_dir, self.configuration_dir_name)
                else:
                    base = device_dir

                self.configuration_dir_path = base
                if name is None:
                    name = self.configuration_name
                    if name is None:
                        name = self.name

                path = os.path.join(base, "{}.yaml".format(name))
                if not os.path.isfile(path):
                    path = os.path.join(base, "{}.yml".format(name))
                    if not os.path.isfile(path):
                        path = os.path.join(base, "{}.cfg".format(name))

        if path is not None and os.path.isfile(path):
            if auto_convert and path.endswith(".cfg"):
                converted = convert_cfg_to_yaml(path)
                if converted:
                    self.info("using yaml configuration {} for legacy {}".format(converted, path))
                    path = converted
                else:
                    self.debug("failed converting {} to yaml. using legacy cfg".format(path))

            config = self.configparser_factory()
            self.debug("loading configuration from {}".format(path))
            config.read(path)
            if set_path:
                self.config_path = path
            return config
        elif warn:
            msg = "{} not a valid initialization file".format(path)
            self.debug(msg)
            self.warning_dialog(msg)

    def get_configuration_writer(self, p=None):
        config = ParserWrapper()
        if p:
            config.read(p)

        return config


# ============= EOF =============================================
