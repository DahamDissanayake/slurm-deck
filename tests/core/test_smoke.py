import importlib

import pytest


@pytest.mark.parametrize("name", ["sdcore", "deckagent", "sdweb"])
def test_packages_import(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__version__ == "2.0.0.dev0"
