# Changelog

## Unreleased

Exports keep `layout_version` 2; exports written by 2.1.0 still import.

### Fixes
- The project directory name now follows Claude Code 2.1.287 exactly: the path is
  NFC-normalised, every non-alphanumeric character becomes `-` (so paths with
  spaces, `~`, `@`, `+`, `(`, `)` or non-ASCII characters are found), names longer
  than 200 characters are truncated and suffixed with Claude Code's hash, and
  `CLAUDE_CODE_PROJECT_DIR_NAME` is honoured together with `CLAUDE_CONFIG_DIR`.
  Previously only `/ \ : . _` were mapped, so such projects were reported as having
  no sessions and imports landed in a directory Claude Code never reads.
- Every command crashed before doing any work on a strict-encoded stdout (Windows
  with output redirected and no `PYTHONUTF8`): unencodable characters are now
  replaced instead of raising.
- `config_snapshot` and `file_history` paths in a manifest were copied without being
  confined to the export directory; `..` and absolute entries are now refused, and
  config entries must also sit under their own `config/<type>/`. Every manifest
  path is checked before anything is written.
- The pre-import snapshot was taken before the transcript was read, so a failed
  import replaced the snapshot of the previous one. Everything that depends on the
  export (reading and rewriting every transcript, sidecar and history record,
  checking every manifest field and path) now happens first; the snapshot is built
  aside and swapped in only when complete, and every write after it is first
  recorded in the snapshot's journal (flushed to disk). Whatever ends an import
  part-way, including SIGTERM or a closed terminal, `ccsession restore --restore`
  removes exactly what was written; a file whose copy never completed is removed
  only if it still holds what the import was copying.
- `ccsession restore --restore` now undoes everything the import added: the
  prompt-history lines the import appended, the imported session's `file-history/`
  directory, the config files and directories the import created and the CLAUDE.md
  note, even a partly written one (later edits to CLAUDE.md and prompt-history lines
  written later are kept, and `history.jsonl` is rewritten atomically with a copy
  kept in the snapshot). The project directory is rebuilt next to itself and swapped
  in, so a restore that fails leaves it as it was; an interrupted restore says how to
  finish, and imports are refused until it has. Its plan separates session files
  that will be deleted from ones that will be rolled back, and the warning says that
  turns added to pre-existing sessions are lost too.
- The CLAUDE.md note is part of the config import, so `--skip-config` leaves
  CLAUDE.md alone, and importing the same export twice adds one note.
- `--quiet` now does what the README says for every command: errors, warnings and
  the final result only. Export, import and restore progress went through bare
  `print` before.
- Skills are exported and imported as directories (`.claude/skills/<name>/SKILL.md`
  with their supporting files); they were looked up as flat `.claude/skills/*.md`
  and silently skipped. Commands, hooks, agents and rules keep sub-directories too.
  A top-level `commands/` folder, which Claude Code does not read, is no longer
  collected.
- `conversation_full.xml` was ill-formed when string-form message content or a
  metadata field carried a control character (ANSI escapes from slash-command
  output); every string is now cleaned.
- List-form tool results (images, MCP results, sub-agent hand-backs) were written to
  the Markdown files as an untruncated Python `repr`; they are rendered block by
  block (images as a short placeholder) and truncated like string results.
- `trajectory.json` keeps content blocks of unknown type (pasted images,
  `redacted_thinking`, ...) under `{"type": "other", "block_type": ..., "payload": ...}`
  instead of dropping them.
- `ccsession export` (no `--session-id`) no longer offers a stale flat
  `agent-*.jsonl` as the main session.
- Identifying the current session no longer writes a `.claude_export_marker` file
  into the project; it compares each transcript's own modification times, and a
  transcript that disappears mid-way is skipped.
- Exporting by `--session-id` a session whose project directory no longer exists
  writes the export under the current directory instead of recreating the old path.
- The `claude --version` probe resolves the executable with `shutil.which` (so npm's
  `claude.cmd` shim is found on Windows), runs with a timeout and a closed stdin, and
  a closed stdin on the `Continue? (y/n)` prompt counts as "no" instead of a
  traceback. `restore --restore` without a terminal and without `--yes` now exits
  with a message instead of a traceback.
- `ccsession restore` validates `snapshot_info.json` and refuses, before changing
  anything, a snapshot that is malformed, was taken for another Claude config
  directory, names a target that is not one of its project directories, or lacks
  its backup copy. It only touches the file-history directory, config files,
  `history.jsonl` and `CLAUDE.md` paths that are exactly where the import put them,
  and never removes a symlink.
- `ccsession --quiet restore` still prints the snapshot summary (it is the
  command's result); `--quiet export` still warns when the export lands under the
  current directory because the project directory is gone.
- On Windows the `claude --version` probe ignores a `claude.cmd`/`claude.exe` found
  in the current directory, which `shutil.which` searches first; an export or
  project directory can no longer supply the program that runs.
- Two imports within the same second no longer overwrite each other's import log.
- A genuine Python import failure (broken installation) is reported as an unexpected
  error with a traceback instead of "Import validation failed".
- JSONL lines that are valid JSON but not objects are skipped instead of crashing
  the export; a string-form message content no longer breaks tool counting.
- Restore messages name the `ccsession` command instead of a `ccsession.py` script.
- With `--preserve-session-id` the manifest's session id became a path component
  unchecked; it must now be a lowercase UUID, so an export cannot make the import
  write outside the Claude config directory.
- A transcript or prompt history holding a lone surrogate escape (`\ud83d`, written
  by `JSON.stringify` when a string is cut inside an emoji) failed to import; such
  values are written back as escapes. The export's prompt history and sub-agent
  transcripts are read before the snapshot, so a malformed export never replaces it.
- Non-object lines in either prompt history are skipped (Claude Code skips them
  too), and a history file whose last line lacks its newline gets one before the
  import appends, instead of merging the user's last prompt with an imported line.
  A history file the import creates is private (0600), like Claude Code's.
- Paths with bytes that are not valid UTF-8 (Linux) are named and recorded the way
  Claude Code does (one U+FFFD per invalid sequence) and never make an import fail.
- File-history snapshots that already exist are never overwritten; a restore
  removes only the ones the import added.
- Restore keeps the project-level entries Claude Code reserves (`memory/`,
  `tiny_memory/`, `bagel/`, `cloud-snapshots/`, `bridge-pointer.json`,
  `.session-aliases`) as they are, keeps the permissions and symlink of
  `history.jsonl`, and the plan names the import the snapshot protects and warns
  (also under `--quiet`) about snapshots older than a day.
- Appends to and rewrites of `history.jsonl` hold Claude Code's own lock
  (`history.jsonl.lock`), write bytes (no CRLF on Windows), keep other lines byte
  for byte, and tolerate history records with unusual field types.
- The CLAUDE.md note follows the file's line endings and is recognised with either
  ending; a dangling `CLAUDE.md` symlink is left alone, and config files are never
  written through a symlink. Files copied from an export are always writable, so a
  read-only or locked file in the export no longer makes the restore fail.
- `CLAUDE_CONFIG_DIR` (and the home directory) are recorded with `..` collapsed, so
  a value such as `../cfg` imports and restores. A 2.1.0 snapshot in
  `~/.claude-session-imports` is only used while the configured storage has never
  been used, so it cannot resurface after a newer restore.
- The project directory must exist; manifests with fields of the wrong type, and
  records nested too deeply to process, are refused before the snapshot.
- An export name must be a single plain directory name (a name such as `tmp/..`
  could make a failed export remove the wrong directory), a failed export only
  removes a directory it created, a prompt history holding a lone surrogate exports,
  and symlinked skill directories (which Claude Code loads) are exported.
- `ccsession export` warnings about guessing the session name the session chosen.
- A failed export no longer leaves a half-written export directory, and records
  with a malformed `message` or `timestamp` are exported as events.
- An unreadable `index.json` no longer stops the import log from being written (it
  is kept as `index.json.corrupt-<time>`), and `snapshot_info.json` and the index
  are written atomically.

### Tooling
- The import storage (`pre-import-snapshot/`, `index.json`, import logs) moves to
  `<CLAUDE_CONFIG_DIR>/ccsession-imports/` when `CLAUDE_CONFIG_DIR` is set, so an
  import into an isolated config directory cannot replace the snapshot protecting
  the default one. The default `~/.claude-session-imports/` is unchanged, and a
  snapshot that 2.1.0 wrote there under `CLAUDE_CONFIG_DIR` is still found (it rolls
  back the project directory only). A relative `CLAUDE_CONFIG_DIR` is made absolute.
- The test suite no longer exports the developer's live sessions: subprocess runs
  use a throwaway `CLAUDE_CONFIG_DIR` and working directory.
- The sdist ships `tests/conftest.py` and the transcript fixture, so its test suite
  runs.
- `scripts/e2e_live.sh` saves the real import storage as soon as it starts and puts
  it back (timestamps included) however the run ends; a failed or interrupted copy
  leaves the storage untouched, and a symlinked storage is followed. It picks the
  session id up front (`claude -p --session-id`) and recovers the imported id from
  the import's output, so a run that fails at any point still removes its sessions,
  file history and prompt-history lines, also under `CLAUDE_CODE_PROJECT_DIR_NAME`.
- Tests clear `CLAUDE_CODE_PROJECT_DIR_NAME` as well as `CLAUDE_CONFIG_DIR`.
- The import storage (snapshot, its journal, import logs and index) is owner-only
  (directories 0700, files 0600): the journal and snapshot hold copies of prompt-history
  lines, which Claude Code keeps private.

## 2.1.0 — 2026-10-14

First release on PyPI as `ccsession-cli` (the import package and the `ccsession`
command are unchanged). Brings ccsession up to the Claude Code 2.1 on-disk format,
verified against transcripts written by Claude Code 2.1.212 through 2.1.287 and a
live export → import → `claude --resume` run.

### Export
- Mirror the whole per-session directory (`session/session-dir/`): sub-agent
  transcripts with their `.meta.json` sidecars, tool-result sidecars, Workflow runs
  and diagnostics.
- Carry the session's `history.jsonl` lines so prompt history follows an import.
- Manifest gains `layout_version` (now 2), `session_dir`, `history` and `agent_meta`.
- `trajectory.json` format 1.1: every record type keeps its payload (`attachment`,
  `last-prompt`, `queue-operation`, `cost-state`, `system`, `file-history-*`), turns
  keep per-turn context under `meta`, sub-agents surface their meta sidecar and link
  to the spawning call through it; statistics add `events_by_type` and `cost_usd`.
- Exporting by `--session-id` snapshots the session's own project, not the shell's
  working directory.
- Legacy plan/todo placeholder files are no longer written when the stores are absent.

### Import
- One reference remapper rewrites every uuid reference (`parentUuid`, `leafUuid`,
  `messageId`, `snapshotMessageId`, `commandUuid`, `logicalParentUuid`,
  `sourceToolAssistantUUID`, `foldedUuids`, `supersedesUuids`, compact metadata, ...),
  rewrites `sessionId`/`session_id` only when they name the imported session, maps each
  and relocates known path fields (with `/` or `\\` separators). Message content and
  sub-agent ids are never touched, so Claude Code's bookkeeping of finished background
  agents keeps working after a resume.
- Sub-agent transcripts, meta sidecars, tool results and workflows are restored into
  `<project>/<new-id>/`; prompt history is appended once.
- Exports from ccsession 2.0.0 (layout 1) and from newer layouts are refused with a
  clear message; the legacy `~/.claude/todos` and `~/.claude/plans` stores and flat
  `agent-*.jsonl` files of older Claude Code releases are no longer read or written.
- The completion message now shows `claude --resume <id>`.

### Fixes
- Sub-agents that were never referenced from the main transcript (background or async
  agents) were silently dropped on export.
- Every sub-agent was attributed to the first Agent call in the trajectory.
- The version check always reported a mismatch (`claude --version` output was
  mis-parsed).
- Session identification never worked on macOS (`ps -o cmd=` is not supported by BSD ps).
- The import conflict message printed a literal `{target_session_path}`.

### Tooling
- `CLAUDE_CONFIG_DIR` is honoured everywhere.
- `scripts/capture_fixture.py` captures a sanitized real session as a test fixture;
  `tests/fixtures/claude-2.1.287/` is the first one.
- `scripts/e2e_live.sh` runs the live end-to-end check against the installed CLI.
- GitHub Actions CI across Linux, macOS and Windows on Python 3.9, 3.12, 3.13 and 3.14;
  tag-triggered publishing through PyPI Trusted Publishing.
- Manifest-supplied paths are confined to the export directory.
