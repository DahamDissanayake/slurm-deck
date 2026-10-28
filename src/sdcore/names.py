"""Username rules for web accounts and their hidden Linux accounts.

A username becomes a Linux account name and a directory under the shared
area (`users/<name>`, `jobs/<name>`), so it must be a safe path segment and
must never collide with a system or service account.
"""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

MAX_LEN = 32

RESERVED: frozenset[str] = frozenset({
    "root", "daemon", "bin", "sys", "nobody",
    "slurm", "slurmadmin", "munge", "mysql", "postgres", "sshd",
    "sdweb", "sdworker", "sd-ops", "sdprov",
    "public", "shared", "admin",
    "gpuusers", "gpuadmins", "webusers", "docker", "sudo",
})

_BAD_CHARS = re.compile(r"[^a-z0-9_-]")


def valid_username(name: str) -> bool:
    """True when name matches USERNAME_RE and isn't a reserved name."""
    return bool(USERNAME_RE.fullmatch(name)) and name not in RESERVED


def suggest_username(email: str, taken: set[str]) -> str:
    """A free, valid username derived from an email's local part.

    Lowercased, other characters become `-`, a name that doesn't start with a
    letter or `_` gets a `u` prefix, and it is cut to 32 characters. A reserved
    or taken result gets `-2`, `-3`, ... (shortening the base to fit).
    """
    base = _BAD_CHARS.sub("-", email.split("@", 1)[0].lower())
    if not base or not (base[0].isascii() and (base[0].isalpha() or base[0] == "_")):
        base = "u" + base
    base = base[:MAX_LEN]
    if valid_username(base) and base not in taken:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[:MAX_LEN - len(suffix)] + suffix
        if valid_username(candidate) and candidate not in taken:
            return candidate
        n += 1
