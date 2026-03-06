# ccsession

Export, import, and restore Claude Code sessions.

Claude Code stores conversation history in `~/.claude/projects/` as JSONL files. ccsession extracts those sessions into portable formats for archival, analysis, or sharing — and can import them back into another environment.

## Install

```bash
pip install -e .
```

## Export

```bash
ccsession export --export-name my-session
```

Exports to `.claude-sessions/my-session/` with:

- `trajectory.json` — structured JSON for analysis (linked tool calls, sub-agents, statistics)
- `RENDERED.md` — human-readable markdown (renders on GitHub)
- `session/main.jsonl` — raw session transcript
- `session/agents/` — sub-agent session files
- `session/tool-results/` — tool-result sidecar files
- `.ccsession-manifest.json` — metadata (required for import)

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
claude -c  # Lists available sessions, including the imported one
```

Import validates the manifest, generates a new session ID, rewrites internal UUIDs while preserving message threading, and copies everything to `~/.claude/projects/`.

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

## Acknowledgments

Based on [cctrace](https://github.com/jimmc414/cctrace) by [@jimmc414](https://github.com/jimmc414).

## License

MIT
