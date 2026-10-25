"""File operations, run by deck-agent as the user (popen_as), one per process:

    python -m deckagent.fsops <op> --user <name> --nfs-root <root> [args]

Path arguments are absolute or relative to the NFS root. Every one is jailed
after resolving symlinks: users read their own area, the shared asset areas
and their own job folders, and write only their own area (--admin, run as
sd-ops, may read and write anywhere under the root). New names must pass the
name rule. JSON goes to stdout except for read and zipstream, which stream
raw bytes; exit 0 ok, 2 refused, 1 failed. Data moves in 1 MiB pieces, never
whole.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterator
from typing import IO, Any

from sdcore.validate import user_browse_roots, user_job_root, user_upload_root

CHUNK = 1024 * 1024
GIB = 2**30
STAGING = ".sd-uploads"
UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
ARCHIVES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz")


class Refused(Exception):
    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


def check_name(name: str) -> str:
    """1-255 bytes of UTF-8, no '/', NUL, CR or LF, and not '.' or '..'."""
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError:
        raise Refused("That name isn't valid text.") from None
    if not 1 <= size <= 255 or name in (".", "..") or any(c in name for c in "/\0\r\n"):
        raise Refused("That name isn't allowed.")
    return name


def _inside(real: str, roots: list[str]) -> bool:
    return any(real == r or real.startswith(r + os.sep) for r in roots)


class Jail:
    def __init__(self, nfs_root: str, user: str, admin: bool) -> None:
        self.root = os.path.realpath(nfs_root)
        if admin:
            self.read_roots = self.write_roots = [self.root]
        else:
            own = user_upload_root(self.root, user)
            self.read_roots = [*user_browse_roots(self.root, user),
                               user_job_root(self.root, user)]
            self.write_roots = [own]
        self.own = self.write_roots[0] if not admin else user_upload_root(self.root, user)

    def _abs(self, path: str) -> str:
        return os.path.join(self.root, path)

    def read(self, path: str) -> str:
        real = os.path.realpath(self._abs(path))
        if not _inside(real, self.read_roots):
            raise Refused("That path is outside your areas.")
        return real

    def write(self, path: str) -> str:
        real = os.path.realpath(self._abs(path))
        if not _inside(real, self.write_roots):
            raise Refused("You can only change files in your own folder.")
        return real

    def entry(self, path: str) -> str:
        """An existing entry to change (rename, delete): its folder is jailed,
        and the entry itself is never followed, so a link is the link."""
        parent, name = os.path.split(self._abs(path).rstrip("/") or "/")
        target = os.path.join(self.write(parent), check_name(name))
        if target in self.write_roots or target == self.root:
            raise Refused("That folder can't be changed.")
        if not os.path.lexists(target):
            raise FileNotFoundError(path)
        return target

    def new(self, path: str) -> str:
        """A path to create: its folder jailed, its name checked."""
        parent, name = os.path.split(self._abs(path))
        return os.path.join(self.write(parent), check_name(name))


def _kind(st: os.stat_result) -> str:
    return "link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode) else "file"


def _info(jail: Jail, path: str, name: str) -> dict[str, Any]:
    st = os.lstat(path)
    readonly = not _inside(os.path.realpath(path), jail.write_roots)
    return {"name": name, "type": _kind(st), "size": st.st_size, "mtime": int(st.st_mtime),
            "readonly": readonly}


def op_list(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    real = jail.read(a.path)
    entries = [_info(jail, os.path.join(real, n), n) for n in os.listdir(real)]
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"]))
    return {"entries": entries}


def op_stat(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    real = jail.read(a.path)
    return _info(jail, real, os.path.basename(real))


def _copy(src: IO[bytes], dst: IO[bytes], limit: int | None = None) -> int:
    done = 0
    while limit is None or done < limit:
        piece = src.read(CHUNK if limit is None else min(CHUNK, limit - done))
        if not piece:
            break
        dst.write(piece)
        done += len(piece)
    return done


def op_read(jail: Jail, a: argparse.Namespace) -> None:
    with open(jail.read(a.path), "rb") as f:
        f.seek(a.offset)
        _copy(f, sys.stdout.buffer, a.limit)


def op_write(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    target = jail.new(a.path)
    data = sys.stdin.buffer.read(a.max + 1)
    if len(data) > a.max:
        raise Refused("That file is too large to edit here.")
    if os.path.isdir(target):
        raise Refused("A folder with that name already exists.")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".sd-tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except BaseException:
        os.unlink(tmp)
        raise
    return {"size": len(data)}


def op_mkdir(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    os.mkdir(jail.new(a.path))
    return {}


def op_rename(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    src, dst = jail.entry(a.src), jail.new(a.dst)
    if os.path.lexists(dst):
        raise Refused("A file with that name already exists.")
    os.rename(src, dst)
    return {}


def op_delete(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    target = jail.entry(a.path)
    if os.path.isdir(target) and not os.path.islink(target):
        if a.recursive:
            shutil.rmtree(target)
        elif os.listdir(target):
            raise Refused("That folder isn't empty.")
        else:
            os.rmdir(target)
    else:
        os.unlink(target)
    return {}


def _part(jail: Jail, upload_id: str) -> str:
    if not UPLOAD_ID.fullmatch(upload_id):
        raise Refused("Bad upload id.")
    staging = os.path.join(jail.own, STAGING)
    os.makedirs(staging, mode=0o700, exist_ok=True)
    return os.path.join(jail.write(staging), upload_id + ".part")


def _size(path: str) -> int:
    try:
        return os.lstat(path).st_size
    except FileNotFoundError:
        return 0


def op_stage_append(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    part = _part(jail, a.upload_id)
    if _size(part) != a.offset:
        raise Refused("The upload offset doesn't match.", size=_size(part))
    fd = os.open(part, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as f:
        _copy(sys.stdin.buffer, f)
    return {"size": _size(part)}


def op_stage_size(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    return {"size": _size(_part(jail, a.upload_id))}


def op_stage_abort(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    part = _part(jail, a.upload_id)
    if os.path.lexists(part):
        os.unlink(part)
    return {}


def op_stage_sweep(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    """Remove this user's staged uploads untouched for max_age_h hours."""
    staging = os.path.join(jail.own, STAGING)
    cutoff, removed = time.time() - a.max_age_h * 3600, 0
    for name in os.listdir(staging) if os.path.isdir(staging) else []:
        path = os.path.join(staging, name)
        if name.endswith(".part") and os.lstat(path).st_mtime < cutoff:
            os.unlink(path)
            removed += 1
    return {"removed": removed}


def op_stage_finalize(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    target = os.path.join(jail.write(a.dest_dir), check_name(a.filename))
    part = _part(jail, a.upload_id)
    if not os.path.isfile(part):
        raise Refused("There is no upload with that id.")
    if os.path.isdir(target):
        raise Refused("A folder with that name already exists.")
    if a.replace:
        os.replace(part, target)
    else:
        try:
            os.link(part, target)   # fails if the name exists: no silent overwrite
        except FileExistsError:
            raise Refused("A file with that name already exists.") from None
        os.unlink(part)
    return {"size": _size(target)}


def _landing(dest: str, name: str) -> str:
    """Where an archive member would land; Refused if it can escape dest."""
    parts = name.replace("\\", "/").split("/")
    if name.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", name) or ".." in parts:
        raise Refused(f"The archive has an unsafe path: {name!r}")
    target = os.path.normpath(os.path.join(dest, *[p for p in parts if p]))
    if not _inside(target, [dest]):
        raise Refused(f"The archive has an unsafe path: {name!r}")
    for p in parts:
        if p:
            check_name(p)
    return target


def _zip_members(z: zipfile.ZipFile, dest: str) -> Iterator[tuple[str, bool, Any]]:
    for info in z.infolist():
        kind = stat.S_IFMT(info.external_attr >> 16)   # 0 when the zip didn't record one
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise Refused(f"The archive has a link or special file: {info.filename!r}")
        yield _landing(dest, info.filename), info.is_dir(), info


def _tar_members(t: tarfile.TarFile, dest: str) -> Iterator[tuple[str, bool, Any]]:
    for m in t:
        if not (m.isreg() or m.isdir()):
            raise Refused(f"The archive has a link or special file: {m.name!r}")
        yield _landing(dest, m.name), m.isdir(), m


def _declared(m: Any) -> int:
    """The unpacked size an archive member says it has."""
    return int(m.file_size if isinstance(m, zipfile.ZipInfo) else m.size)


def _copy_member(data: IO[bytes], target: str, declared: int, name: str) -> None:
    """Write one member to a new file, refusing (and removing the file) if it
    holds more bytes than it declared."""
    with open(target, "xb") as out:
        try:
            if _copy(data, out, declared + 1) > declared:
                raise Refused(f"The archive member {name!r} is larger than it says.")
        except BaseException:
            out.close()
            os.unlink(target)
            raise


def op_extract(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    archive, dest = jail.read(a.archive), jail.write(a.dest_dir)
    lower = archive.lower()
    if not lower.endswith(ARCHIVES):
        raise Refused("That isn't a supported archive (.zip, .tar, .tar.gz, .tgz, .tar.xz).")
    is_zip = lower.endswith(".zip")

    def members() -> Iterator[tuple[str, bool, Any]]:
        if is_zip:
            with zipfile.ZipFile(archive) as z:
                yield from _zip_members(z, dest)
        else:
            with tarfile.open(archive, "r:*") as t:
                yield from _tar_members(t, dest)

    # First pass checks every member, so a bad archive extracts nothing.
    total = 0
    for target, is_dir, m in members():
        if not is_dir and os.path.lexists(target):
            raise Refused(f"{os.path.relpath(target, dest)} already exists.")
        total += 0 if is_dir else _declared(m)
    if a.max_bytes is not None and total > a.max_bytes:
        raise Refused(f"That archive is too large to extract here ({total} bytes unpacked).")
    st = os.statvfs(dest)
    if total + a.margin > st.f_bavail * st.f_frsize:
        raise Refused("There isn't enough free space on the cluster to extract that archive "
                      f"({total} bytes unpacked).")
    count = 0
    opener: Any = zipfile.ZipFile(archive) if is_zip else tarfile.open(archive, "r:*")
    with opener as src:
        for target, is_dir, m in (_zip_members(src, dest) if is_zip else _tar_members(src, dest)):
            if is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            data = src.open(m) if is_zip else src.extractfile(m)
            with data:
                _copy_member(data, target, _declared(m), os.path.relpath(target, dest))
            count += 1
    return {"files": count}


def _walk(base: str) -> Iterator[tuple[str, str, bool]]:
    """(path, name in the zip, is_dir) under base, never following links."""
    parent = os.path.dirname(base)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)))
        if dirpath != base:
            yield dirpath, os.path.relpath(dirpath, parent) + "/", True
        for f in sorted(filenames):
            path = os.path.join(dirpath, f)
            if not os.path.islink(path) and os.path.isfile(path):
                yield path, os.path.relpath(path, parent), False


def op_zipstream(jail: Jail, a: argparse.Namespace) -> None:
    real = jail.read(a.path)
    items = [(real, os.path.basename(real), False)] if os.path.isfile(real) else _walk(real)
    # An unseekable stdout makes zipfile write data descriptors: no size limit, no temp file.
    with zipfile.ZipFile(sys.stdout.buffer, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for path, name, is_dir in items:
            if is_dir:
                z.writestr(zipfile.ZipInfo(name), b"")
                continue
            with open(path, "rb") as f, z.open(name, "w", force_zip64=True) as out:
                _copy(f, out)


def op_du(jail: Jail, a: argparse.Namespace) -> dict[str, Any]:
    real = jail.read(a.path)
    total = os.lstat(real).st_size
    for dirpath, dirnames, filenames in os.walk(real):
        for n in dirnames + filenames:
            total += os.lstat(os.path.join(dirpath, n)).st_size
    return {"bytes": total}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deckagent.fsops")
    sub = p.add_subparsers(dest="op", required=True)

    def add(name: str, *args: str) -> argparse.ArgumentParser:
        s = sub.add_parser(name)
        s.add_argument("--user", required=True)
        s.add_argument("--nfs-root", required=True)
        s.add_argument("--admin", action="store_true")
        for arg in args:
            s.add_argument(arg)
        return s

    for name in ("list", "stat", "mkdir", "zipstream", "du"):
        add(name, "path")
    r = add("read", "path")
    r.add_argument("--offset", type=int, default=0)
    r.add_argument("--limit", type=int)
    add("write", "path").add_argument("--max", type=int, default=CHUNK)
    add("rename", "src", "dst")
    add("delete", "path").add_argument("--recursive", action="store_true")
    add("stage-append", "upload_id").add_argument("--offset", type=int, required=True)
    add("stage-finalize", "upload_id", "dest_dir", "filename").add_argument(
        "--replace", action="store_true")
    add("stage-abort", "upload_id")
    add("stage-size", "upload_id")
    add("stage-sweep").add_argument("--max-age-h", type=int, default=24)
    x = add("extract", "archive", "dest_dir")
    x.add_argument("--max-bytes", type=int)            # optional cap on the unpacked total
    x.add_argument("--margin", type=int, default=GIB)  # free space left after extracting
    return p


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        jail = Jail(a.nfs_root, a.user, a.admin)
        result = globals()["op_" + a.op.replace("-", "_")](jail, a)
    except Refused as e:
        print(json.dumps({"ok": False, "error": str(e), **e.extra}))
        return 2
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as e:
        print(json.dumps({"ok": False, "error": str(e) or type(e).__name__}))
        return 1
    if result is not None:
        print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
