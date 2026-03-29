from __future__ import annotations

import yaml


class _BlockStringDumper(yaml.SafeDumper):
    """Custom SafeDumper that uses block style (|) for multiline strings."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_representer(str, self._str_representer)

    def _str_representer(self, dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
        if "\n" in data:
            escaped_data = data.replace("\n---\n", "\n...\n")
            escaped_data = escaped_data.replace(" \n", "\n")
            return dumper.represent_scalar(
                "tag:yaml.org,2002:str", escaped_data, style="|"
            )
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def dump_yaml(
    data: dict,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    allow_unicode: bool = True,
) -> str:
    return yaml.dump(
        data,
        default_flow_style=default_flow_style,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
        Dumper=_BlockStringDumper,
    )
