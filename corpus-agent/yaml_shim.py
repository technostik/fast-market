from __future__ import annotations

import json
import sys
from importlib import import_module as _import_module
from types import ModuleType
from typing import Any

_real_yaml: ModuleType | None = None
for _name, _mod in list(sys.modules.items()):
    if _name == "yaml" and _mod is not None:
        _real_yaml = _mod
        break
else:
    _real_yaml = _import_module("yaml")


def _as_text(data: Any) -> str:
    if hasattr(data, "read"):
        return data.read()
    return str(data)


def safe_load(text: Any):
    return _real_yaml.safe_load(_as_text(text))


def load(stream: Any, Loader: Any = None):  # noqa: N803
    if Loader is None:
        Loader = _real_yaml.FullLoader
    return _real_yaml.load(_as_text(stream), Loader)


def full_load(stream: Any):
    return _real_yaml.full_load(_as_text(stream))


def safe_dump(obj, stream=None, **kwargs) -> str:
    dumped = json.dumps(obj, indent=2, ensure_ascii=False)
    if stream is None:
        return dumped
    stream.write(dumped)
    return dumped


def dump(obj, stream=None, **kwargs) -> str:
    return safe_dump(obj, stream=stream, **kwargs)


def safe_load_all(stream: Any):
    return _real_yaml.safe_load_all(_as_text(stream))


def dump_all(documents, stream=None, **kwargs):
    return _real_yaml.dump_all(documents, stream, **kwargs)
