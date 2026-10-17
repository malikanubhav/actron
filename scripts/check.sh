#!/usr/bin/env bash
set -euo pipefail
uv run --group dev mypy actron
uv run --group dev ruff check actron tests
uv run --group dev pytest
