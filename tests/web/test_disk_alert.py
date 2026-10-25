"""The disk-full alert: once per 24 hours, only above the admin's threshold."""

from datetime import UTC, datetime, timedelta

import pytest
from accounts_helpers import _account
from sqlalchemy import func, select, text

from sdweb.models import OutboxMessage
from sdweb.worker import disk_task

pytestmark = pytest.mark.pg
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


class DiskAgent:
    def __init__(self, used_percent: int) -> None:
        self.used = used_percent * 10

    def call(self, verb, payload=None, *, session=None):
        assert verb == "cluster.disk_free" and session is None
        return {"total_bytes": 1000, "used_bytes": self.used, "free_bytes": 1}


def test_active_admins_are_mailed_once_in_24_hours_and_only_over_the_threshold(env):
    app = env[0]
    with app.state.sessionmaker() as s, s.begin():   # tables the shared fixture doesn't reset
        s.execute(text("TRUNCATE outbox"))
        s.execute(text("DELETE FROM settings WHERE key IN ('last_disk_alert_at', 'disk_alert_percent')"))
    for name, role, status in (("dinuka", "admin", "active"), ("kasun", "admin", "active"),
                               ("amasha", "user", "active"), ("gone", "admin", "disabled")):
        _account(app, name, role=role, status=status)

    def run(percent, when):
        with app.state.sessionmaker() as s, s.begin():
            return disk_task.run_once(s, DiskAgent(percent), when, app.state.settings)

    def mails():
        with app.state.sessionmaker() as s:
            return s.scalar(select(func.count()).select_from(OutboxMessage))

    assert run(89, T0) == 0 and mails() == 0   # under the default 90%
    assert run(95, T0) == 2 and mails() == 2   # the two active admins
    assert run(99, T0 + timedelta(hours=23)) == 0 and mails() == 2
    assert run(95, T0 + timedelta(hours=24, minutes=1)) == 2 and mails() == 4
