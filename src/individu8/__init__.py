"""individu8 — deterministic hashing of Python dicts, lists, and JSON/YAML strings."""

import sys
from typing import Any

from individu8.core import individu8 as _individu8

__version__ = "0.1.1"


class _Module(sys.modules[__name__].__class__):
    def __call__(self, *args: Any, **kwargs: Any) -> str | list[str]:
        return _individu8(*args, **kwargs)


sys.modules[__name__].__class__ = _Module
