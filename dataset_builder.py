#!/usr/bin/env python3
"""Root entrypoint for M0ST dataset pipeline."""

from data.datasets.scripts.dataset_builder import main


if __name__ == "__main__":
    raise SystemExit(main())
