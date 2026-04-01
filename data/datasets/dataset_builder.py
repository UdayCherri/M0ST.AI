"""Compatibility wrapper for the dataset builder CLI and API.

Primary implementation lives in data/datasets/scripts/dataset_builder.py.
"""

from data.datasets.scripts.dataset_builder import (  # noqa: F401
	DATASET_SIZE_TARGETS,
	DEFAULT_COMPILE_VARIANTS,
	DEFAULT_COMPILERS,
	DEFAULT_OPT_LEVELS,
	DEFAULT_PROJECT_SPECS,
	DatasetBuilder,
	MERGE_WEIGHTS,
	ProjectSpec,
	main,
)


__all__ = [
	"DATASET_SIZE_TARGETS",
	"DEFAULT_COMPILE_VARIANTS",
	"DEFAULT_COMPILERS",
	"DEFAULT_OPT_LEVELS",
	"DEFAULT_PROJECT_SPECS",
	"DatasetBuilder",
	"MERGE_WEIGHTS",
	"ProjectSpec",
	"main",
]

