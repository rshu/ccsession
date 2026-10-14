# ccsession

[![CI](https://github.com/rshu/ccsession/actions/workflows/ci.yml/badge.svg)](https://github.com/rshu/ccsession/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ccsession-cli?cacheSeconds=3600)](https://pypi.org/project/ccsession-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/ccsession-cli?cacheSeconds=3600)](https://pypi.org/project/ccsession-cli/)
[![Downloads](https://img.shields.io/pypi/dm/ccsession-cli?cacheSeconds=3600)](https://pypistats.org/packages/ccsession-cli)
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

## Export

```bash
ccsession export --export-name my-session
```

Exports to `.claude-sessions/my-session/` with:

- `trajectory.json` — structured JSON for analysis (format 1.1: every record's payload,
  per-turn `meta`, sub-agents with their meta sidecar and spawning tool call, statistics)
- `RENDERED.md` — human-readable markdown (renders on GitHub)
- `session/main.jsonl` — raw session transcript
- `session/session-dir/` — verbatim mirror of `<project>/<session-id>/`: sub-agent
  transcripts and `.meta.json` sidecars, tool-result sidecars, Workflow runs, diagnostics
- `session/history.jsonl` — the session's prompt-history lines
- `session/file-history/`, `session/session-env/` — file snapshots and session env
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
appends the prompt history, and copies file snapshots. A pre-import snapshot is taken
first. Paths recorded inside tool inputs, `wireToolInputs` and file-history backups keep
the original machine's paths, so `/rewind` cannot match files after a move to a new
project path.

```bash
# Import into a different project
ccsession import .claude-sessions/my-session/ --project-path /path/to/project

# Skip config or auxiliary files
ccsession import .claude-sessions/my-session/ --skip-config
ccsession import .claude-sessions/my-session/ --skip-auxiliary
```

## Restore

If an import causes problems:

```bash
ccsession restore           # Show snapshot info
ccsession restore --restore # Restore pre-import state
```

## Flags

```bash
ccsession --quiet export ...    # Errors and success only
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
