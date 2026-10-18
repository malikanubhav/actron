import pytest

from tests.fakes.llm import isolated_models, jev_on, jev_sleeps, llm_on, usage_rows

__all__ = ["isolated_models", "jev_on", "jev_sleeps", "llm_on", "usage_rows"]


@pytest.fixture(autouse=True)
def _models_isolated(isolated_models: None) -> None:
    """Every model test starts with no keys, no cache and a list usage sink."""
