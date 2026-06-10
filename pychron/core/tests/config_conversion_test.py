import os
import shutil
import tempfile
import unittest

try:
    from pychron.config_conversion import (
        convert_cfg_to_yaml,
        convert_directory,
        parse_value,
        yaml_sibling_path,
    )
    from pychron.config_mixin import ConfigMixin, YAMLParser
    from pychron.core.yaml import yload
except ModuleNotFoundError as e:
    convert_cfg_to_yaml = None
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


CFG_TEXT = """[General]
name = bone
timeout = 5
scale = 1.25
enabled = true
address = 01

[Communications]
type = serial
port = /dev/tty.usbserial
baudrate = 9600
"""


class _ConfigHarness(ConfigMixin if convert_cfg_to_yaml else object):
    logger = None
    name = "harness"

    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def debug(self, msg):
        self.messages.append(("debug", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def warning_dialog(self, msg):
        self.messages.append(("warning_dialog", msg))


@unittest.skipIf(convert_cfg_to_yaml is None, "PyYAML is not installed")
class ParseValueTestCase(unittest.TestCase):
    def test_booleans(self):
        self.assertIs(parse_value("true"), True)
        self.assertIs(parse_value("Yes"), True)
        self.assertIs(parse_value("ON"), True)
        self.assertIs(parse_value("false"), False)
        self.assertIs(parse_value("No"), False)
        self.assertIs(parse_value("off"), False)

    def test_numbers(self):
        self.assertEqual(parse_value("42"), 42)
        self.assertEqual(parse_value("-7"), -7)
        self.assertEqual(parse_value("3.14"), 3.14)

    def test_leading_zero_stays_string(self):
        self.assertEqual(parse_value("01"), "01")

    def test_strings(self):
        self.assertEqual(parse_value("hello"), "hello")
        self.assertEqual(parse_value("1,2,3"), "1,2,3")
        self.assertEqual(parse_value("/dev/tty.usbserial"), "/dev/tty.usbserial")


@unittest.skipIf(convert_cfg_to_yaml is None, "PyYAML is not installed")
class ConvertCfgToYamlTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.root, "bone.cfg")
        with open(self.cfg_path, "w") as wfile:
            wfile.write(CFG_TEXT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_conversion_creates_typed_yaml(self):
        yp = convert_cfg_to_yaml(self.cfg_path)
        self.assertEqual(yp, yaml_sibling_path(self.cfg_path))
        self.assertTrue(os.path.isfile(yp))
        # original is untouched
        self.assertTrue(os.path.isfile(self.cfg_path))

        obj = yload(yp)
        self.assertEqual(obj["General"]["name"], "bone")
        self.assertEqual(obj["General"]["timeout"], 5)
        self.assertEqual(obj["General"]["scale"], 1.25)
        self.assertIs(obj["General"]["enabled"], True)
        self.assertEqual(obj["General"]["address"], "01")
        self.assertEqual(obj["Communications"]["baudrate"], 9600)

    def test_existing_yaml_wins(self):
        yp = yaml_sibling_path(self.cfg_path)
        with open(yp, "w") as wfile:
            wfile.write("General:\n  name: existing\n")

        result = convert_cfg_to_yaml(self.cfg_path)
        self.assertEqual(result, yp)
        self.assertEqual(yload(yp)["General"]["name"], "existing")

    def test_overwrite(self):
        yp = yaml_sibling_path(self.cfg_path)
        with open(yp, "w") as wfile:
            wfile.write("General:\n  name: existing\n")

        result = convert_cfg_to_yaml(self.cfg_path, overwrite=True)
        self.assertEqual(result, yp)
        self.assertEqual(yload(yp)["General"]["name"], "bone")

    def test_invalid_cfg_returns_none(self):
        bad = os.path.join(self.root, "bad.cfg")
        with open(bad, "w") as wfile:
            wfile.write("not an ini file\n")
        self.assertIsNone(convert_cfg_to_yaml(bad))
        self.assertFalse(os.path.isfile(yaml_sibling_path(bad)))

    def test_convert_directory(self):
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        other = os.path.join(sub, "other.cfg")
        with open(other, "w") as wfile:
            wfile.write(CFG_TEXT)

        results = dict(convert_directory(self.root))
        self.assertEqual(results[self.cfg_path], yaml_sibling_path(self.cfg_path))
        self.assertEqual(results[other], yaml_sibling_path(other))


@unittest.skipIf(convert_cfg_to_yaml is None, "PyYAML is not installed")
class YAMLParserTestCase(unittest.TestCase):
    def setUp(self):
        self.parser = YAMLParser(
            {
                "General": {"name": "bone", "enabled": False, "count": 0},
                "Communications": {"type": "serial", "baudrate": 9600},
            }
        )

    def test_sections(self):
        self.assertEqual(self.parser.sections(), ["General", "Communications"])
        self.assertTrue(self.parser.has_section("General"))
        self.assertFalse(self.parser.has_section("Nope"))

    def test_has_option_with_falsy_values(self):
        # False/0 values must still register as present
        self.assertTrue(self.parser.has_option("General", "enabled"))
        self.assertTrue(self.parser.has_option("General", "count"))
        self.assertFalse(self.parser.has_option("General", "missing"))
        self.assertFalse(self.parser.has_option("Nope", "missing"))

    def test_options_missing_section(self):
        self.assertEqual(self.parser.options("Nope"), [])

    def test_casts(self):
        self.assertEqual(self.parser.getint("Communications", "baudrate"), 9600)
        self.assertEqual(self.parser.getfloat("Communications", "baudrate"), 9600.0)
        self.assertIs(self.parser.getboolean("General", "enabled"), False)

    def test_getboolean_string_value(self):
        parser = YAMLParser({"General": {"enabled": "false"}})
        self.assertIs(parser.getboolean("General", "enabled"), False)

    def test_set_and_write_roundtrip(self):
        self.parser.add_section("New")
        self.parser.set("New", "value", 1.5)

        root = tempfile.mkdtemp()
        try:
            path = os.path.join(root, "out.yaml")
            with open(path, "w") as wfile:
                self.parser.write(wfile)
            obj = yload(path)
            self.assertEqual(obj["New"]["value"], 1.5)
            self.assertEqual(obj["General"]["name"], "bone")
        finally:
            shutil.rmtree(root, ignore_errors=True)


@unittest.skipIf(convert_cfg_to_yaml is None, "PyYAML is not installed")
class GetConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.root, "bone.cfg")
        with open(self.cfg_path, "w") as wfile:
            wfile.write(CFG_TEXT)
        self.harness = _ConfigHarness()
        self.harness.config_path = self.cfg_path

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cfg_auto_converted_to_yaml(self):
        config = self.harness.get_configuration()
        self.assertIsNotNone(config)

        yp = yaml_sibling_path(self.cfg_path)
        self.assertTrue(os.path.isfile(yp))
        self.assertEqual(self.harness.config_path, yp)

        self.assertEqual(config.get("General", "name"), "bone")
        self.assertEqual(config.getfloat("General", "scale"), 1.25)
        self.assertIs(config.getboolean("General", "enabled"), True)
        self.assertEqual(self.harness.config_get(config, "General", "timeout", cast="int"), 5)

    def test_auto_convert_disabled_reads_cfg(self):
        config = self.harness.get_configuration(auto_convert=False)
        self.assertIsNotNone(config)
        self.assertEqual(self.harness.config_path, self.cfg_path)
        self.assertFalse(os.path.isfile(yaml_sibling_path(self.cfg_path)))
        # raw ConfigParser semantics: values are strings
        self.assertEqual(config.get("General", "timeout"), "5")

    def test_yaml_config_write_roundtrip(self):
        config = self.harness.get_configuration()
        config.set("General", "timeout", 10)
        self.harness.write_configuration(config)

        reloaded = self.harness.get_configuration()
        self.assertEqual(reloaded.getint("General", "timeout"), 10)

    def test_missing_falsy_option_uses_default(self):
        config = self.harness.get_configuration()
        config.set("General", "flag", False)
        # a stored False must be returned, not swallowed as "missing"
        self.assertIs(
            self.harness.config_get(
                config, "General", "flag", cast="boolean", optional=True, default=True
            ),
            False,
        )


if __name__ == "__main__":
    unittest.main()
