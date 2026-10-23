# Phase 4 — Files and Uploads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser file manager over each user's private area and the read-only shared areas, with resumable uploads of hundreds of GB, file and folder downloads, extraction, and a file picker the New job flow uses.

**Architecture:** Every file operation runs in a short-lived `python -m deckagent.fsops` subprocess **as the user** (admins as `sd-ops`), started by deck-agent through `popen_as`. Uploads use the tus 1.0 protocol in `web`; each PATCH body streams straight through deck-agent into a staging file on `/shared`, authorised by an HMAC grant deck-agent issued after one full session check.

**Tech Stack:** as Phase 2; tus-js-client in the frontend.

**Spec:** §4.4 (upload), §6.5, §6.6, §13 scenario 2. **Roadmap:** fixed values (`UPLOAD_CHUNK_MB` 64, `UPLOAD_RESUME_HOURS` 24).

## Global Constraints

- Roadmap constraints apply.
- Browse roots = `user_browse_roots(nfs_root, username)` (own area + `/shared/models`, `/shared/envs`, `/shared/data`, `/shared/datasets`), plus read-only `/shared/jobs/<username>`. Writes only inside `/shared/users/<username>`. Shared areas are read-only for users regardless of POSIX bits.
- No trash: delete is permanent after a confirmation dialog.
- Nothing is written inside the containers; no chunk is buffered whole in memory (stream in ≤ 1 MiB pieces).
- Free-space guard: refuse an upload when `size + 1 GiB` exceeds free bytes on `/shared`; copy: "There isn't enough free space on the cluster for this upload ({free} free, {needed} needed)."
- Folder-of-small-files hint copy: "Zip first — 1 million small files upload far slower than one archive."
- Text editing limited to files ≤ 1 MiB that decode as UTF-8.

## Review Focus

- **Upload resumed from a different browser tab or after the session expired** — resume works after signing in again within 24 h because the grant is reissued from the upload row; a different account cannot resume it. Test in Task 3.
- **Two uploads finishing to the same filename** — second finalize must not overwrite; it's refused with "A file with that name already exists." unless the user chose Replace. Test in Task 1.
- **Archive containing `../` or absolute paths or symlinks** — refused before extracting anything. Test in Task 1.
- **Filenames with unicode, spaces, `%`, `#`, newlines** — listed, downloaded and renamed correctly; newline/NUL/`/` refused in new names. Test in Task 1 and Task 4.
- **Download of a 200 GB folder** — streams as zip without a size limit or temp file; the browser can cancel. Test in Task 4 (size simulated).

---

### Task 1: `deckagent.fsops` — file operations as the user

**Files:**
- Create: `src/deckagent/fsops.py`, `tests/agent/test_fsops.py`
- Source: `legacy/v1.4-tui:slurmdeck/upload.py::_unzip_in_folder` (traversal checks), `slurmdeck/files.py` (listing).

**Interfaces:**
- Produces: CLI `python -m deckagent.fsops <op> --user <name> --nfs-root <root> [args]`, JSON on stdout (except streaming ops), exit 0/2 (refused)/1 (error). Ops:
  - `list <path>` → `{"entries":[{"name","type":"file|dir|link","size","mtime","readonly":bool}]}` sorted dirs first, then name.
  - `stat <path>`; `read <path> --offset N --limit N` (raw bytes to stdout); `write <path> --max 1048576` (stdin → atomic temp + rename, only inside own area).
  - `mkdir <path>`; `rename <src> <dst>` (same or different dir within own area; refuses existing `dst`); `delete <path> --recursive` (refuses roots themselves).
  - `stage-append <upload_id> --offset N` (stdin appended to `<own>/.sd-uploads/<upload_id>.part`; refuses when current size ≠ offset; prints new size).
  - `stage-finalize <upload_id> <dest_dir> <filename> [--replace]`; `stage-abort <upload_id>`; `stage-size <upload_id>`.
  - `extract <archive> <dest_dir>` for `.zip`, `.tar`, `.tar.gz`/`.tgz`, `.tar.xz`: pre-scan every member; refuse if any is absolute, contains `..`, is a symlink/hardlink/device, or would land outside `dest_dir`; then extract streaming.
  - `zipstream <path>` → ZIP_STORED zip of a dir (or the single file) to stdout using data descriptors; follows no symlinks.
  - `du <path>` → `{"bytes"}`.
  - Name rule for new names: 1–255 bytes UTF-8, no `/`, NUL, `\n`, `\r`, not `.`/`..`.
  - Every path argument is resolved (`os.path.realpath`) and must lie under an allowed root for the op (read vs write) — checked again after resolution, so symlinks can't escape.

- [ ] **Step 1:** Tests (run the module directly as the current user on a tmp tree with `--nfs-root tmp`):
  ```python
  def test_symlink_escape_refused(tree): ...                # users/a/link -> users/b ; list users/a/link → exit 2
  def test_write_outside_own_area_refused(tree): ...         # write datasets/x → 2
  @pytest.mark.parametrize("member", ["../x", "/etc/passwd", "a/../../x"])
  def test_extract_refuses_traversal(tree, member): ...      # nothing extracted at all
  def test_extract_refuses_symlink_member(tree): ...
  def test_finalize_refuses_existing_without_replace(tree): ...
  def test_stage_append_rejects_wrong_offset(tree): ...
  def test_zipstream_is_a_valid_zip(tree): ...               # zipfile.ZipFile(io.BytesIO(out)).namelist()
  @pytest.mark.parametrize("name", ["a\nb", "a/b", "..", ""])
  def test_bad_new_names_refused(tree, name): ...
  def test_unicode_and_spaces_roundtrip(tree): ...           # "données 50% #1.csv"
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add jailed file operations helper run as the user`.

---

### Task 2: deck-agent file verbs and upload grants

**Files:**
- Create: `src/deckagent/verbs/files.py`, `src/deckagent/grants.py`, `src/deckagent/janitor.py`, `tests/agent/test_verbs_files.py`, `tests/agent/test_grants.py`

**Interfaces:**
- Consumes: Task 1; Phase 1 `popen_as`, `identity_for_user`, `ops_identity`.
- Produces:
  - `grants.issue(key: bytes, *, username: str, upload_id: str, expires: int) -> str` and `grants.verify(key, grant: str, *, upload_id: str, now: int) -> str` (returns username; raises `AgentError("bad_grant", 403)`); HMAC-SHA256 over `username|upload_id|expires`, base64url; key from `SD_GRANT_KEY_FILE` (32 random bytes, root 0600, created by the installer).
  - Verbs (user; admin additionally may pass `as_admin: true` to act via `sd-ops` on any user's area for read/list/download/delete):
    `fs.list {path}`, `fs.stat {path}`, `fs.read {path, offset, limit}` (stream), `fs.write {path}` (raw body ≤ 1 MiB), `fs.mkdir {path}`, `fs.rename {src, dst}`, `fs.delete {path, recursive}`, `fs.extract {archive, dest_dir}`, `fs.download_stream {path}` (raw; file → bytes, dir → zipstream; `Content-Disposition` filename), `fs.du {path}`, `fs.free_space` → `{free_bytes, total_bytes}`.
    Upload: `fs.upload_begin {upload_id, dest_dir, filename, size}` → checks free space rule and dest writability → `{grant, offset}`; `fs.upload_regrant {upload_id}` (session must be the same username) → `{grant, offset}`; `fs.write_chunk` (headers `X-SD-Grant`, `X-SD-Upload`, `X-SD-Offset`; raw body streamed into `stage-append` stdin in 1 MiB reads) → `{offset}`; `fs.upload_finalize {upload_id, replace}` → `{path}`; `fs.upload_abort {upload_id}`.
  - Grants expire after 6 h; `fs.write_chunk` needs no session (the grant carries identity).
  - `janitor` thread in deck-agent: every hour deletes `.sd-uploads/*.part` older than `UPLOAD_RESUME_HOURS` (24) across `/shared/users/*` via `fsops` as each owner.

- [ ] **Step 1:** Tests: grant for user A rejected for upload id of B; expired grant rejected; tampered grant rejected; free-space refusal with the exact copy (fake `statvfs`); admin `as_admin` list of another user works, non-admin `as_admin` → 403; `write_chunk` streams 5 MB without the agent process growing > 20 MB RSS.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add deck-agent file verbs, upload grants and staging janitor`.

---

### Task 3: tus upload endpoint in `web`

**Files:**
- Create: `src/sdweb/files/__init__.py`, `src/sdweb/files/tus.py`, `src/sdweb/migrations/versions/0005_uploads.py`, `tests/web/test_tus.py`

**Interfaces:**
- Consumes: Task 2 verbs via `AgentClient.call` / `upload_chunk`.
- Produces:
  - Table `uploads(id uuid pk, account_id fk, dest_dir, filename, size bigint, offset bigint, created_at, expires_at, finished_at null, aborted_at null, grant text, grant_expires_at)`.
  - tus 1.0.0 with `creation` and `termination` extensions at `/api/uploads`:
    - `OPTIONS` → `Tus-Resumable: 1.0.0`, `Tus-Version: 1.0.0`, `Tus-Extension: creation,termination`, `Tus-Max-Size` = free bytes − 1 GiB.
    - `POST` (session + CSRF) headers `Upload-Length`, `Upload-Metadata` (`filename`, `dest_dir`, `replace` base64) → agent `fs.upload_begin`; `201` + `Location: /api/uploads/<id>`.
    - `HEAD /api/uploads/{id}` (owner session) → `Upload-Offset` from agent `stage-size`; regrants when the stored grant expires within 10 min.
    - `PATCH /api/uploads/{id}` (owner session + CSRF; `Content-Type: application/offset+octet-stream`; `Upload-Offset` must equal stored offset else 409) → streams `request.stream()` to `AgentClient.upload_chunk`; updates `offset`; when `offset == size` calls `fs.upload_finalize` and sets `finished_at`; `204` + `Upload-Offset`.
    - `DELETE` → `fs.upload_abort`.
  - Uploads older than 24 h are expired (404 on HEAD/PATCH).
  - `GET /api/uploads?active=1` → the account's unfinished uploads (so the UI can offer Resume after a reload).

- [ ] **Step 1:** Tests (fake agent storing bytes): a 3-chunk upload finalizes and the bytes match; PATCH with a stale offset → 409; a second account's HEAD → 404; resume after 23 h works, after 25 h → 404; PATCH body of 64 MB streams with < 16 MB process growth.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add tus resumable uploads streaming through deck-agent`.

---

### Task 4: Files API

**Files:**
- Create: `src/sdweb/files/routes.py`, `tests/web/test_files_api.py`

**Interfaces:**
- Produces (session; CSRF on writes):
  - `GET /api/files/roots` → `[{label, path, writable}]` ("My files", "Shared datasets", "Shared models", "Shared environments", "Shared data", "My job outputs").
  - `GET /api/files?path=` → list; `GET /api/files/stat?path=`.
  - `GET /api/files/download?path=` → streamed (`Content-Disposition: attachment; filename*=UTF-8''…`); dirs as `<name>.zip`.
  - `GET /api/files/preview?path=` → images (png/jpg/gif/webp ≤ 20 MB) inline; CSV/TSV first 50 rows as JSON; text first 64 KiB.
  - `GET /api/files/text?path=` / `PUT /api/files/text?path=` (≤ 1 MiB UTF-8).
  - `POST /api/files/mkdir {path}`, `POST /api/files/rename {src, dst}`, `POST /api/files/delete {path, recursive}`, `POST /api/files/extract {archive, dest_dir}`.
  - Admin: same endpoints with `?user=<username>` → agent `as_admin`.

- [ ] **Step 1:** Tests: download filename with unicode/`#`/`%` is encoded per RFC 5987; a client disconnect mid-download stops the agent stream (fake agent records close); non-admin `?user=` → 403; text PUT of 1 MiB + 1 byte → 413.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add files API for browse, preview, edit, download and extract`.

---

### Task 5: Frontend — Files page, uploads, FilePicker

**Files:**
- Create: `frontend/src/api/files.ts`, `frontend/src/pages/Files.tsx`, `frontend/src/components/FileTable.tsx`, `frontend/src/components/Breadcrumbs.tsx`, `frontend/src/components/UploadPanel.tsx`, `frontend/src/components/FilePicker.tsx`, `frontend/src/components/TextEditor.tsx`, `frontend/src/components/Preview.tsx`, tests alongside.
- Modify: `frontend/src/pages/NewJob/StepInputs.tsx` (replace script/data/model path text inputs with `FilePicker`).

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces:
  - Files page: roots in the sidebar, breadcrumb, sortable table (name, size, modified), toolbar (New folder, Upload files, Upload folder, Download, Rename, Move, Delete, Extract when an archive is selected), read-only badge on shared areas, preview drawer, `TextEditor` (monospace `<textarea>`, Save, unsaved-changes guard).
  - `UploadPanel`: tus-js-client with `chunkSize = 64 * 1024 * 1024`, `retryDelays [0, 1000, 3000, 5000, 10000, 30000]`, `headers: {"X-CSRF-Token": …}`, `metadata {filename, dest_dir, replace}`, fingerprint stored so a reload offers Resume (`GET /api/uploads?active=1`); per-file progress with speed and time left; Pause/Resume/Cancel; folder upload via `webkitdirectory` (shows the zip-first hint when > 1 000 files); "Extract after upload" checkbox for archives; free-space refusal shown verbatim.
  - `FilePicker({mode: "file"|"dir", accept?: string[], onPick(path)})` modal reusing `FileTable`.

- [ ] **Step 1:** Vitest: zip-first hint appears for 1 001 files; Delete requires confirmation; read-only area hides write actions; FilePicker returns an absolute `/shared/...` path; TextEditor warns on navigation with unsaved changes.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add file manager, resumable upload panel and file picker`.

---

## Phase exit check

- [ ] On the test VM over wired LAN: upload a 20 GB file, kill the browser at ~50 %, reopen, resume, finish; record throughput in the PR (spec §16 risk). Extract an archive, download a folder as zip, confirm another user can't list or download the folder.
