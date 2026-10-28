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
    # Check real markers, not item.keywords: keywords also hold parametrize ids,
    # so a case parametrized with "root" would be skipped as a root test.
    for item in items:
        if item.get_closest_marker("root") and not root_ok:
            item.add_marker(skip_root)
        if item.get_closest_marker("pg") and not pg_ok:
            item.add_marker(skip_pg)
