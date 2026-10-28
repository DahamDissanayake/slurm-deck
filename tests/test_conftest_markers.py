import pytest


@pytest.mark.parametrize("name", ["root", "pg"])
def test_parametrize_ids_named_like_markers_still_run(name: str) -> None:
    # Fails by being skipped: the conftest once matched markers by keyword.
    assert name in ("root", "pg")
