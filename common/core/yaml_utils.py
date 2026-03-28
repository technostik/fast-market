from __future__ import annotations

import yaml
from yaml import dump as _yaml_dump

_multiline_representer_added = False


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def dump_yaml(
    data: dict,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    allow_unicode: bool = True,
) -> str:
    global _multiline_representer_added
    if not _multiline_representer_added:
        yaml.SafeDumper.add_representer(str, _str_representer)
        _multiline_representer_added = True

    return _yaml_dump(
        data,
        default_flow_style=default_flow_style,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
    )
