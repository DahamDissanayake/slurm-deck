"""The disk-full alert: once per 24 hours, only above the admin's threshold."""

from datetime import UTC, datetime, timedelta

import pytest
from accounts_helpers import _account
from sqlalchemy import func, select, text

from sdweb.models import OutboxMessage, Setting
from sdweb.worker import disk_task

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


class DiskAgent:
    def __init__(self, used_percent: int) -> None:
        self.used_percent = used_percent

    def call(self, verb, payload=None, *, session=None):
        assert verb == "cluster.disk_free" and session is None
        return {"total_bytes": 1000, "used_bytes": self.used_percent * 10, "free_bytes": 1}


@pytest.fixture
def alerts(env):
    app, _, _ = env
    with app.state.sessionmaker() as s, s.begin():   # tables the shared fixture doesn't reset
        s.execute(text("TRUNCATE outbox"))
        s.execute(text("DELETE FROM settings WHERE key IN ('last_disk_alert_at', "
                       "'disk_alert_percent')"))
    _account(app, "dinuka", role="admin")
    _account(app, "kasun", role="admin")
    _account(app, "amasha")
    _account(app, "gone", role="admin", status="disabled")

    def run(percent, when):
        with app.state.sessionmaker() as s, s.begin():
            return disk_task.run_once(s, DiskAgent(percent), when, app.state.settings)

    def mails():
        with app.state.sessionmaker() as s:
            return s.scalar(select(func.count()).select_from(OutboxMessage).where(
                OutboxMessage.kind == "disk_alert"))
    return app, run, mails


def test_active_admins_are_mailed_once_in_24_hours(alerts):
    _, run, mails = alerts
    assert run(95, T0) == 2 and mails() == 2
    assert run(96, T0 + timedelta(hours=1)) == 0 and run(99, T0 + timedelta(hours=23)) == 0
    assert mails() == 2
    assert run(95, T0 + timedelta(hours=24, minutes=1)) == 2 and mails() == 4


def test_nothing_is_sent_below_the_threshold_or_when_the_admin_raises_it(alerts):
    app, run, mails = alerts
    assert run(89, T0) == 0
    with app.state.sessionmaker() as s, s.begin():
        s.merge(Setting(key="disk_alert_percent", value=97))
    assert run(95, T0) == 0 and mails() == 0
    assert run(97, T0) == 2
