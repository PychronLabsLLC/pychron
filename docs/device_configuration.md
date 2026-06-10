# Device Configuration

YAML is the preferred configuration format for devices and other
`ConfigMixin` consumers. Legacy ConfigParser/INI `.cfg` files are still
supported and are converted to YAML automatically the first time they are
loaded.

## File Resolution

When a device looks up its configuration (`ConfigMixin.get_configuration`),
files in the device directory (`setupfiles/devices` by default) are tried in
this order:

1. `<name>.yaml` (preferred)
2. `<name>.yml`
3. `<name>.cfg` (legacy)

## Format

A YAML device configuration mirrors the section/option structure of the old
INI format, but with real types:

```yaml
General:
  name: bone_micro
Communications:
  type: serial
  port: /dev/tty.usbserial
  baudrate: 38400
  timeout: 0.25
```

The equivalent legacy `.cfg`:

```ini
[General]
name = bone_micro

[Communications]
type = serial
port = /dev/tty.usbserial
baudrate = 38400
timeout = 0.25
```

## On-the-fly Conversion

When `get_configuration` resolves to a `.cfg` file, it converts the file to a
sibling `.yaml` file and loads the YAML instead. The original `.cfg` is left
in place, so the conversion is non-destructive and reversible (delete the
`.yaml` and pass `auto_convert=False` to fall back). If a sibling `.yaml`
already exists, it wins and the `.cfg` is ignored.

Conversion performs best-effort typing: `true/false/yes/no/on/off` become
booleans, integer and float strings become numbers, and anything ambiguous
(e.g. values with leading zeros like `01`) stays a string.

Once converted, any configuration written back by the application (e.g.
auto-found serial handles) is written to the YAML file.

## Batch Conversion

To convert an entire device directory ahead of time:

```bash
python -m pychron.config_conversion ~/Pychron/setupfiles/devices
```

Options: `--overwrite` regenerates existing `.yaml` files, `--no-recursive`
limits the scan to the top directory. A single file path also works.

## Programmatic API

- `pychron.config_conversion.convert_cfg_to_yaml(path)` — convert one file,
  returns the YAML path (or the pre-existing sibling YAML) or `None` on
  failure.
- `pychron.config_conversion.convert_directory(root)` — batch convert,
  returns `(cfg_path, yaml_path_or_None)` tuples.
- `pychron.config_mixin.YAMLParser` — ConfigParser-compatible adapter used by
  `ConfigMixin`, so device code written against the ConfigParser API
  (`has_section`, `config_get`, `set_attribute`, casts, `set`/`write`) works
  unchanged with YAML files.
- `pychron.hardware.config_template.ConfigTemplate.to_yaml_config_content` —
  generate new device configs in YAML from a template.
