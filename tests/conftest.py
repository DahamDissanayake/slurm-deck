import os
import shutil

import pytest


def _is_root_with_useradd() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0 and shutil.which("useradd") is not None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_root = pytest.mark.skip(reason="needs root and useradd")
    skip_pg = pytest.mark.skip(reason="needs TEST_DATABASE_URL")
    root_ok = _is_root_with_useradd()
    pg_ok = bool(os.environ.get("TEST_DATABASE_URL"))
    for item in items:
        if "root" in item.keywords and not root_ok:
            item.add_marker(skip_root)
        if "pg" in item.keywords and not pg_ok:
            item.add_marker(skip_pg)
