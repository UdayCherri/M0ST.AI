"""Dataset builder scripts for M0ST."""

from importlib import import_module
from typing import Any


__all__ = [
    "DATASET_SIZE_TARGETS",
    "DEFAULT_COMPILERS",
    "DEFAULT_OPT_LEVELS",
    "DEFAULT_PROJECT_SPECS",
    "DatasetBuilder",
    "ProjectSpec",
    "main",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = import_module("data.datasets.scripts.dataset_builder")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
