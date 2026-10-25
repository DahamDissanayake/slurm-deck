"""The session-origin ticket store: one-time codes and per-job tickets."""

from sdweb.proxy.tickets import Tickets


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_code_is_single_use_and_names_its_job():
    t = Tickets(clock=Clock())
    code = t.issue("raw-session", "notebook", "42", ttl_s=3600)
    ticket = t.redeem(code)
    assert ticket is not None and ticket.kind == "notebook" and ticket.job_id == "42"
    assert t.redeem(code) is None                      # spent
    assert t.session_token(ticket.id, "notebook", "42") == "raw-session"


def test_ticket_is_bound_to_its_kind_and_job():
    t = Tickets(clock=Clock())
    ticket = t.redeem(t.issue("raw", "notebook", "42", ttl_s=3600))
    assert ticket is not None
    assert t.session_token(ticket.id, "notebook", "43") is None
    assert t.session_token(ticket.id, "terminal", "42") is None
    assert t.session_token("forged", "notebook", "42") is None


def test_code_and_ticket_expire():
    clock = Clock()
    t = Tickets(clock=clock)
    code = t.issue("raw", "notebook", "42", ttl_s=3600)
    clock.now += t.CODE_TTL_S + 1
    assert t.redeem(code) is None                      # too late to enter
    ticket = t.redeem(t.issue("raw", "notebook", "42", ttl_s=3600))
    assert ticket is not None
    clock.now += 3601
    assert t.session_token(ticket.id, "notebook", "42") is None


def test_ids_are_long_and_random():
    t = Tickets(clock=Clock())
    codes = {t.issue("raw", "notebook", "42", ttl_s=60) for _ in range(50)}
    assert len(codes) == 50 and all(len(c) >= 40 for c in codes)
