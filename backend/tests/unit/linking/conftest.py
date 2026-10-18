import pytest

from tests.fakes.llm import isolated_models, jev_on, jev_sleeps, llm_on, usage_rows

__all__ = ["isolated_models", "jev_on", "jev_sleeps", "llm_on", "usage_rows"]


@pytest.fixture(autouse=True)
def _models_isolated(isolated_models: None) -> None:
    """Linking tests start with no model keys (stubs) unless a test turns on a fake."""
