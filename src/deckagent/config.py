"""deck-agent settings, read from its environment file (agent.env)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    socket_path: str
    db_ro_url: str
    nfs_root: str
    web_uid: int
    worker_uid: int
    webusers_group: str
    gpuusers_group: str
    admin_group: str
    ops_user: str
    slurm_bin: str
    slurm_account: str
    slurm_qos: str
    partition: str
    compute_node: str
    stats_file: str
    gpu_helper_ssh: str
    gpu_helper_key: str
    grant_key_file: str
    audit_log: str
    web_uid_min: int
    web_uid_max: int
    max_workers: int
    request_deadline_s: int
    max_json_bytes: int


def _int(env: Mapping[str, str], key: str, default: int | None = None) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"{key} is required")
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from None


def load_config(env: Mapping[str, str]) -> AgentConfig:
    nfs_root = env.get("SD_NFS_ROOT") or "/shared"
    return AgentConfig(
        socket_path=env.get("SD_AGENT_SOCKET") or "/run/slurm-deck-web/agent.sock",
        db_ro_url=env.get("SD_DB_RO_URL", ""),
        nfs_root=nfs_root,
        web_uid=_int(env, "SD_WEB_UID"),
        worker_uid=_int(env, "SD_WORKER_UID"),
        webusers_group=env.get("SD_WEBUSERS_GROUP") or "webusers",
        gpuusers_group=env.get("SD_GPUUSERS_GROUP") or "gpuusers",
        admin_group=env.get("SD_ADMIN_GROUP") or "gpuadmins",
        ops_user=env.get("SD_OPS_USER") or "sd-ops",
        slurm_bin=env.get("SD_SLURM_BIN") or "/usr/bin",
        slurm_account=env.get("SD_SLURM_ACCOUNT") or "default",
        slurm_qos=env.get("SD_SLURM_QOS") or "normal",
        partition=env.get("SD_PARTITION") or "gpu",
        compute_node=env.get("SD_COMPUTE_NODE", ""),
        stats_file=env.get("SD_STATS_FILE") or f"{nfs_root.rstrip('/')}/.gpu_stats.json",
        gpu_helper_ssh=env.get("SD_GPU_HELPER_SSH", ""),
        gpu_helper_key=env.get("SD_GPU_HELPER_KEY", ""),
        grant_key_file=env.get("SD_GRANT_KEY_FILE", ""),
        audit_log=env.get("SD_AUDIT_LOG") or "/var/log/slurm-deck-web/agent-audit.jsonl",
        web_uid_min=_int(env, "SD_WEB_UID_MIN", 20000),
        web_uid_max=_int(env, "SD_WEB_UID_MAX", 59999),
        max_workers=_int(env, "SD_MAX_WORKERS", 8),
        request_deadline_s=_int(env, "SD_REQUEST_DEADLINE_S", 30),
        max_json_bytes=_int(env, "SD_MAX_JSON_BYTES", 1024 * 1024),
    )
