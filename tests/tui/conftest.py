import pytest

from .factories import FakeSource, make_source


@pytest.fixture
def source() -> FakeSource:
    return make_source()


@pytest.fixture(autouse=True)
def _colour_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
