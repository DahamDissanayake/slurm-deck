import pytest

from sdcore.names import RESERVED, USERNAME_RE, suggest_username, valid_username


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "Root", "root", "slurmadmin", "9abc",
                                 "x" * 33, "sdweb", "-abc", "a b", "a.b", "sd-ops", "admin"])
def test_invalid_usernames(bad: str) -> None:
    assert not valid_username(bad)


@pytest.mark.parametrize("good", ["amasha", "a", "_svc", "amasha-perera", "u123", "x" * 32,
                                  "a_b-c9"])
def test_valid_usernames(good: str) -> None:
    assert valid_username(good)


def test_username_regex_is_the_documented_rule() -> None:
    assert USERNAME_RE.pattern == r"^[a-z_][a-z0-9_-]{0,31}$"


def test_reserved_names_cover_system_and_service_accounts() -> None:
    for name in ("root", "slurm", "slurmadmin", "munge", "postgres", "sdweb", "sdworker",
                 "sd-ops", "sdprov", "gpuusers", "gpuadmins", "webusers", "docker", "sudo"):
        assert name in RESERVED


def test_suggest_username() -> None:
    assert suggest_username("Amasha.Perera@iit.ac.lk", set()) == "amasha-perera"
    assert suggest_username("amasha@x.com", {"amasha"}) == "amasha-2"
    assert suggest_username("123@x.com", set()) == "u123"


def test_suggest_username_counts_up_past_taken_suffixes() -> None:
    assert suggest_username("amasha@x.com", {"amasha", "amasha-2", "amasha-3"}) == "amasha-4"


def test_suggest_username_avoids_reserved_names() -> None:
    assert suggest_username("root@x.com", set()) == "root-2"
    assert suggest_username("Admin@x.com", set()) == "admin-2"


def test_suggest_username_truncates_to_32_with_room_for_suffix() -> None:
    first = suggest_username("a" * 40 + "@x.com", set())
    assert first == "a" * 32
    second = suggest_username("a" * 40 + "@x.com", {first})
    assert second == "a" * 30 + "-2"
    assert valid_username(second)


def test_suggest_username_always_valid() -> None:
    for email in ("first+tag@x.com", "-dash@x.com", "@x.com", "ünï@x.com", "a..b@x", "x"):
        name = suggest_username(email, set())
        assert valid_username(name), (email, name)
