# Changelog

## 2.1.0 — 2026-10-14

First release on PyPI as `ccsession-cli` (the import package and the `ccsession`
command are unchanged). Brings ccsession up to the Claude Code 2.1 on-disk format,
verified against transcripts written by Claude Code 2.1.212 through 2.1.287 and a
live export → import → `claude --resume` run.

### Export
- Mirror the whole per-session directory (`session/session-dir/`): sub-agent
  transcripts with their `.meta.json` sidecars, tool-result sidecars, Workflow runs
  and diagnostics. Legacy flat-layout agents are normalised into the same mirror.
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
