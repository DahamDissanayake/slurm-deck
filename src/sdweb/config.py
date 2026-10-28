"""Web settings, read from the environment (web.env plus secrets.env).

Site values (hostname, cluster name, timezone, mail) come from here; the fixed
values from the spec (session limits, lockout, link lives) have defaults that
a site can override. Settings an admin changes at run time live in the
`settings` table instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAIL_PROVIDERS = ("resend", "smtp", "none")


@dataclass(frozen=True)
class WebSettings:
    database_url: str
    agent_socket: str
    public_hostname: str
    cluster_name: str
    cluster_tz: str
    mail_provider: str
    mail_from: str
    resend_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_starttls: bool
    secure_cookies: bool
    session_idle_minutes: int
    session_max_hours: int
    password_min_len: int
    lockout_fails: int
    lockout_window_min: int
    lockout_min: int
    set_link_hours: int
    reset_link_hours: int
    expiry_warn_minutes: int
    web_uid_min: int
    web_uid_max: int
    nfs_root: str
    partition: str
    jupyter_env: str = "/shared/envs/jupyter"
    session_ports: tuple[int, int] = (8800, 8999)
    env_spec_dir: str = "/app/cluster/envs"
    lan_addr: str = ""   # the address users reach, for the hosts-file hint
    # Interactive sessions are served from this hostname, never the app's own,
    # so a job's pages can't reach the platform cookie or API.
    session_hostname: str = ""


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key) or ""
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from None


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{key} must be true or false, got {raw!r}")


def _port_range(env: Mapping[str, str]) -> tuple[int, int]:
    raw = env.get("SESSION_PORT_RANGE") or "8800-8999"
    lo, _, hi = raw.partition("-")
    try:
        ports = int(lo), int(hi)
    except ValueError:
        raise ValueError(f"SESSION_PORT_RANGE must look like 8800-8999, got {raw!r}") from None
    if not 1024 <= ports[0] <= ports[1] <= 65535:
        raise ValueError(f"SESSION_PORT_RANGE must be unprivileged ports, low-high: {raw!r}")
    return ports


def load_settings(env: Mapping[str, str]) -> WebSettings:
    database_url = env.get("SD_DATABASE_URL") or ""
    if not database_url:
        raise ValueError("SD_DATABASE_URL is required")
    tz = env.get("SD_CLUSTER_TZ") or "UTC"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"SD_CLUSTER_TZ is not an IANA timezone: {tz!r}") from None
    mail = env.get("SD_MAIL_PROVIDER") or "none"
    if mail not in MAIL_PROVIDERS:
        raise ValueError(f"SD_MAIL_PROVIDER must be one of {', '.join(MAIL_PROVIDERS)}")
    public_hostname = env.get("SD_PUBLIC_HOSTNAME") or "slurmdeck.local"
    session_hostname = (env.get("SD_SESSION_HOSTNAME") or f"sessions.{public_hostname}").lower()
    if session_hostname == public_hostname.lower():
        raise ValueError("SD_SESSION_HOSTNAME must differ from SD_PUBLIC_HOSTNAME")
    return WebSettings(
        database_url=database_url,
        agent_socket=env.get("SD_AGENT_SOCKET") or "/run/slurm-deck-web/agent.sock",
        public_hostname=public_hostname,
        cluster_name=env.get("SD_CLUSTER_NAME") or "Slurm Deck",
        cluster_tz=tz,
        mail_provider=mail,
        mail_from=env.get("SD_MAIL_FROM", ""),
        resend_api_key=env.get("SD_RESEND_API_KEY", ""),
        smtp_host=env.get("SD_SMTP_HOST", ""),
        smtp_port=_int(env, "SD_SMTP_PORT", 587),
        smtp_user=env.get("SD_SMTP_USER", ""),
        smtp_password=env.get("SD_SMTP_PASSWORD", ""),
        smtp_starttls=_bool(env, "SD_SMTP_STARTTLS", True),
        secure_cookies=_bool(env, "SD_SECURE_COOKIES", True),
        session_idle_minutes=_int(env, "SESSION_IDLE_MINUTES", 30),
        session_max_hours=_int(env, "SESSION_MAX_HOURS", 12),
        password_min_len=_int(env, "PASSWORD_MIN_LEN", 12),
        lockout_fails=_int(env, "LOCKOUT_FAILS", 10),
        lockout_window_min=_int(env, "LOCKOUT_WINDOW_MIN", 15),
        lockout_min=_int(env, "LOCKOUT_MIN", 15),
        set_link_hours=_int(env, "SET_LINK_HOURS", 24),
        reset_link_hours=_int(env, "RESET_LINK_HOURS", 1),
        expiry_warn_minutes=_int(env, "EXPIRY_WARN_MINUTES", 30),
        web_uid_min=_int(env, "SD_WEB_UID_MIN", 20000),
        web_uid_max=_int(env, "SD_WEB_UID_MAX", 59999),
        nfs_root=env.get("SD_NFS_ROOT") or "/shared",
        partition=env.get("SD_PARTITION") or "gpu",
        jupyter_env=env.get("SD_JUPYTER_ENV")
        or f"{(env.get('SD_NFS_ROOT') or '/shared').rstrip('/')}/envs/jupyter",
        session_ports=_port_range(env),
        env_spec_dir=env.get("SD_ENV_SPEC_DIR") or "/app/cluster/envs",
        lan_addr=env.get("SD_LAN_ADDR", ""),
        session_hostname=session_hostname,
    )
