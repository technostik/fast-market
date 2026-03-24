from __future__ import annotations

import yaml_shim as yaml


def test_yaml_shim_exposes_dump_and_safe_dump():
    assert hasattr(yaml, "dump")
    assert hasattr(yaml, "safe_dump")

    dumped = yaml.dump({"a": 1})
    assert isinstance(dumped, str)


def test_yaml_shim_load_variants():
    text = "key: value"
    assert yaml.safe_load(text)["key"] == "value"
    assert yaml.load(text)["key"] == "value"
    assert yaml.full_load(text)["key"] == "value"
