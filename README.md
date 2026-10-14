# ccsession

[![CI](https://github.com/rshu/ccsession/actions/workflows/ci.yml/badge.svg)](https://github.com/rshu/ccsession/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ccsession-cli?cacheSeconds=3600)](https://pypi.org/project/ccsession-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/ccsession-cli?cacheSeconds=3600)](https://pypi.org/project/ccsession-cli/)
[![Downloads](https://static.pepy.tech/badge/ccsession-cli/month)](https://pepy.tech/projects/ccsession-cli)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Export, import, and restore Claude Code sessions.

Claude Code stores conversation history in `~/.claude/projects/` as JSONL files. ccsession extracts those sessions into portable formats for archival, analysis, or sharing — and can import them back into another environment.

## Install

```bash
pip install ccsession-cli
```

The package installs the `ccsession` command. For development, `pip install -e ".[dev]"`.

## Compatibility

Tested against transcripts written by Claude Code 2.1.212 through 2.1.287 and against a
live export → import → `claude --resume` run with 2.1.287. It understands the current
layout (per-session `subagents/` with `.meta.json` sidecars, `tool-results/`,
`workflows/`, `history.jsonl`) and record types (`attachment`, `last-prompt`,
`queue-operation`, `cost-state`, `file-history-snapshot`/`delta`, `system`, ...).
`CLAUDE_CONFIG_DIR` is honoured. Older Claude Code layouts (`~/.claude/todos`, `~/.claude/plans`,
flat `agent-*.jsonl` files) and exports made by ccsession 2.0.0 are not supported.

Sessions are looked up under `<claude-dir>/projects/<name>/` using Claude Code's own
naming rule (the path is NFC-normalised, every non-alphanumeric character becomes
`-`, long names are truncated and hashed); `CLAUDE_CODE_PROJECT_DIR_NAME` is honoured
together with `CLAUDE_CONFIG_DIR`, as in Claude Code.

## Export

```bash
ccsession export --export-name my-session
```

Exports to `.claude-sessions/my-session/` under the project (or under the current
directory when the session's project directory no longer exists) with:

- `trajectory.json` — structured JSON for analysis (format 1.1: every record's payload,
  per-turn `meta`, sub-agents with their meta sidecar and spawning tool call, statistics)
- `RENDERED.md` — human-readable markdown (renders on GitHub)
- `session/main.jsonl` — raw session transcript
- `session/session-dir/` — verbatim mirror of `<project>/<session-id>/`: sub-agent
  transcripts and `.meta.json` sidecars, tool-result sidecars, Workflow runs, diagnostics
- `session/history.jsonl` — the session's prompt-history lines
- `session/file-history/`, `session/session-env/` — file snapshots and session env
- `config/` — the project's `.claude/` configuration: `commands/`, `skills/`,
  `hooks/`, `agents/` and `rules/` mirrored with their sub-directories (skills are
  `skills/<name>/SKILL.md` plus supporting files), and `settings.json` and `CLAUDE.md`
  for reference (import does not restore those two)
- `.ccsession-manifest.json` — metadata (required for import; `layout_version` 2)

```bash
# Export a specific session by ID
ccsession export --session-id f33cdb42-0a41-40d4-91eb-c89c109af38a

# Export to a custom directory
ccsession export --output-dir /path/to/output --export-name my-session

# Legacy format (flat files to ~/claude_sessions/exports/)
ccsession export --mode classic
```

## Import

```bash
ccsession import .claude-sessions/my-session/
claude --resume <new-session-id>   # printed at the end of the import
```

Import validates the manifest, generates a new session id, rewrites every internal
reference consistently (message uuids wherever they appear outside message content,
session ids, recorded paths) without touching message content or sub-agent ids,
restores the sub-agent transcripts, sidecars and workflows under `<project>/<new-id>/`,
appends the prompt history, copies file snapshots, restores config files that do not
exist yet under `<project>/.claude/` and appends an import note to `CLAUDE.md`.
Existing files are never overwritten: config files and file-history snapshots that
are already there are skipped. `settings.json` and `CLAUDE.md` from the export are
not restored (hook scripts copied into `.claude/hooks/` therefore stay inactive until
you wire them up). Every path named by the manifest is confined to the export
directory, and with `--preserve-session-id` the session id must be a lowercase UUID.
Everything is read and checked before the pre-import snapshot is taken, nothing is
written before it, and every write is first recorded in the snapshot's journal. The
project directory must exist. Paths
recorded inside tool inputs, `wireToolInputs` and file-history backups keep the
original machine's paths, so `/rewind` cannot match files after a move to a new
project path. Run one import at a time: concurrent imports share the single snapshot
slot and the import index.

```bash
# Import into a different project
ccsession import .claude-sessions/my-session/ --project-path /path/to/project

# Skip config files and the CLAUDE.md note, or file/prompt history
ccsession import .claude-sessions/my-session/ --skip-config
ccsession import .claude-sessions/my-session/ --skip-auxiliary
```

## Restore

If an import causes problems:

```bash
ccsession restore                 # Show what the snapshot covers
ccsession restore --restore       # Roll back the last import (asks for confirmation)
ccsession restore --restore --yes # Same without the prompt (needed when stdin is not a terminal)
```

A restore puts `<claude-dir>/projects/<project>/` back the way it was before the
import — sessions created since are deleted and sessions that existed before are
rolled back, including turns added to them afterwards — and then undoes the rest of
the import: the prompt-history lines the import appended, the file-history snapshots
it added, the config files and directories it created, and the CLAUDE.md note.
The project-level entries Claude Code keeps under the project directory (auto-memory
in `memory/`, and `tiny_memory/`, `bagel/`, `cloud-snapshots/`,
`bridge-pointer.json`, `.session-aliases`) are kept as they are now, as are later
edits to `CLAUDE.md` and prompt-history lines written later (including prompts typed
into the imported session); `history.jsonl` keeps its permissions and, if it is a
symlink, the link. The plan is printed before anything is deleted, and a restore
refuses to run if the snapshot is malformed, was taken for another Claude config
directory or names anything other than one of its project directories. The project
directory is rebuilt next to itself and swapped in, so a restore that fails leaves
it untouched; rerun `ccsession restore --restore` after fixing the cause (imports
are refused until that restore has finished). One snapshot is kept, of the most
recent import, and a new one replaces it only once it is complete; an import that
fails part-way, however it ends, has journaled what it wrote, so the same restore
cleans it up. Close Claude Code sessions in that project before restoring.

The snapshot and import logs live in `~/.claude-session-imports/`, or in
`<CLAUDE_CONFIG_DIR>/ccsession-imports/` when `CLAUDE_CONFIG_DIR` is set (a relative
value is taken relative to the current directory). A snapshot written by ccsession
2.1.0 is still found in `~/.claude-session-imports/` when `CLAUDE_CONFIG_DIR` is set
and its own storage has never been used, and rolls back the project directory only.

## Flags

```bash
ccsession --quiet export ...    # Errors, warnings and the final result only
ccsession --verbose export ...  # Detailed output
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

`tests/fixtures/claude-2.1.287/` is a sanitized real session captured with
`scripts/capture_fixture.py <session-id> <out-dir>`; the round-trip test exports and
re-imports it and checks that every reference still resolves. To refresh the fixture for
a newer Claude Code, run a session and capture it the same way.

`scripts/e2e_live.sh` runs the full loop against the installed `claude` CLI (creates a
throwaway project, lets `claude -p` fix a bug with a sub-agent, exports, imports into a
second project, resumes with `claude -p --resume`). It needs a logged-in CLI and spends
usage, so it is not part of the test suite.

## Acknowledgments

Based on [cctrace](https://github.com/jimmc414/cctrace) by [@jimmc414](https://github.com/jimmc414).

## License

MIT
