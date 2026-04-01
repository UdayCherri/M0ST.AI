"""Tests for dataset builder helpers and repeatable output behavior."""

import tempfile
import unittest
from pathlib import Path

from data.datasets.scripts.dataset_builder import DatasetBuilder


class TestDatasetBuilderHelpers(unittest.TestCase):
    """Unit tests for dataset builder utility methods."""

    def test_resolve_compiler_output_path_prefers_existing_target(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "sample_bin"
            output.write_bytes(b"binary")

            resolved = DatasetBuilder._resolve_compiler_output_path(output)

            self.assertEqual(resolved, output)

    def test_resolve_compiler_output_path_finds_windows_exe(self):
        with tempfile.TemporaryDirectory() as td:
            requested = Path(td) / "sample_bin"
            exe_output = Path(f"{requested}.exe")
            exe_output.write_bytes(b"binary")

            resolved = DatasetBuilder._resolve_compiler_output_path(requested)

            self.assertEqual(resolved, exe_output)

    def test_extract_variant_metadata_parses_stripped_synthetic_variant(self):
        builder = DatasetBuilder(root_dir="data/datasets")
        binary_path = Path(
            "data/datasets/stripped/"
            "synthetic_bubble_sort_000_O2_gcc_stripped/"
            "bubble_sort_000_O2_gcc.exe"
        )

        metadata = builder._extract_variant_metadata(binary_path)

        self.assertEqual(metadata["source_project"], "synthetic_bubble_sort_000")
        self.assertEqual(metadata["compiler"], "gcc")
        self.assertEqual(metadata["optimization_level"], "O2")


class TestDatasetBuilderGraphOutputReset(unittest.TestCase):
    """Ensure repeated graph builds do not leave stale serialized outputs behind."""

    def test_clear_existing_graph_outputs_removes_old_graphs_and_resets_counter(self):
        with tempfile.TemporaryDirectory() as td:
            builder = DatasetBuilder(root_dir=td)
            builder.ensure_layout()
            builder._function_counter = 42

            stale_graph = builder.graphs_dir / "func_999999.pt"
            stale_graph.write_bytes(b"stale")

            builder._clear_existing_graph_outputs()

            self.assertEqual(builder._function_counter, 0)
            self.assertFalse(stale_graph.exists())


if __name__ == "__main__":
    unittest.main()
