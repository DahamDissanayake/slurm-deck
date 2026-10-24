"""Passwords (argon2id), password rules, tokens and email addresses."""

from __future__ import annotations

import re
import secrets
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from deckagent.sessions import hash_token

__all__ = ["hash_password", "verify_password", "needs_rehash", "password_problems",
           "new_token", "hash_token", "normalize_email", "valid_email"]

PASSWORD_MIN_LEN = 12
COMMON_PASSWORDS = Path(__file__).resolve().parent / "auth" / "common-passwords.txt"

_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash: str, pw: str) -> bool:
    try:
        return _hasher.verify(hash, pw)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hash: str) -> bool:
    return _hasher.check_needs_rehash(hash)


@cache
def _common() -> frozenset[str]:
    lines = COMMON_PASSWORDS.read_text(encoding="utf-8").splitlines()
    return frozenset(x for x in lines if x and not x.startswith("#"))


def password_problems(pw: str, *, email: str, username: str) -> list[str]:
    """Every rule the password breaks, as messages to show; [] when it is fine."""
    problems = []
    if len(pw) < PASSWORD_MIN_LEN:
        problems.append(f"Use at least {PASSWORD_MIN_LEN} characters.")
    lowered = pw.lower()
    if lowered in _common():
        problems.append("That password is too common.")
    email = normalize_email(email)
    personal = [username.lower(), email, email.partition("@")[0]]
    if any(len(p) >= 3 and p in lowered for p in personal):
        problems.append("Don't use your email or username.")
    return problems


def new_token() -> str:
    """43 URL-safe characters (32 random bytes): session, CSRF and link tokens."""
    return secrets.token_urlsafe(32)


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


_EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


def valid_email(addr: str) -> bool:
    """One @, a non-empty local part, a dotted domain, no whitespace, at most 254."""
    return len(addr) <= 254 and _EMAIL.fullmatch(addr) is not None
