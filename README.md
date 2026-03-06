# ccsession

Export, import, and restore Claude Code sessions.

Claude Code stores conversation history in `~/.claude/projects/<normalized-path>/*.jsonl`. ccsession extracts those sessions into portable formats for archival, analysis, or sharing — and can import them back into another environment.

## Export Modes

### Portable Export (default)

Exports to `.claude-sessions/<name>/` within your repository.

```bash
ccsession export --export-name my-session
```

```
.claude-sessions/my-session/
├── .ccsession-manifest.json    # Required for import
├── trajectory.json           # Clean JSON for analysis
├── RENDERED.md               # Renders on GitHub
├── session/
│   ├── main.jsonl            # Session transcript
│   ├── agents/               # Sub-agent session files
│   ├── tool-results/         # Tool-result sidecar files
│   ├── file-history/         # File snapshots from undo history
│   ├── todos.json            # Todo state
│   └── plan.md               # Plan file if present
├── config/
│   ├── commands/             # Slash commands
│   ├── skills/               # Skills
│   └── ...                   # Other .claude/ config
└── [legacy files]            # For backwards compatibility
```

### Trajectory (included by default)

Every portable export includes a `trajectory.json` — a clean, self-contained JSON file designed for programmatic analysis, evaluation, and benchmarking.

The trajectory transforms raw JSONL into a structured format with:
- **Ordered entries** — messages become turns with `role`, `timestamp`, and `content`; non-message JSONL lines (progress, system, file-history-snapshot) become `role: "event"` entries
- **Linked tool calls** — `tool_use` becomes `tool_call` (with `caller`), `tool_result` references `tool_call_id`
- **Full tool execution** — `toolUseResult` passed through as-is with all fields (`durationMs`, `stdout`, `stderr`, `filePath`, etc.)
- **Thinking with signatures** — thinking blocks include `signature` for verification
- **Inline sub-agents** — agent sessions are nested with their own trajectory arrays
- **Pre-computed statistics** — turn counts, event counts, tool call breakdown, token usage
- **Clean metadata** — session info, models used, duration, git branch

### Classic Export

Exports to `~/claude_sessions/exports/` with timestamped directories.

```bash
ccsession export --mode classic
```

```
~/claude_sessions/exports/2025-07-02_16-45-00_f33cdb42/
├── raw_messages.jsonl     # Original session data
├── conversation_full.md   # Human-readable markdown
├── conversation_full.xml  # Structured XML with full metadata
├── session_info.json      # Session metadata
└── summary.txt            # Statistics
```

## Importing a Session

Someone clones your repo and wants to continue your session:

```bash
ccsession import .claude-sessions/my-session/
claude -c  # Lists available sessions, including the imported one
```

### What Import Does

1. Validates the export has a `.ccsession-manifest.json`
2. Creates a pre-import snapshot for recovery
3. Generates a new session ID (your local sessions remain unaffected)
4. Rewrites internal UUIDs while preserving message threading
5. Updates `cwd` paths to the local project directory
6. Copies session file to `~/.claude/projects/<normalized-path>/`
7. Imports auxiliary data (file-history, todos, plans)
8. Imports config files (commands, skills, hooks, agents, rules)

### What Import Preserves

Certain fields are cryptographically signed or tied to Anthropic's API and must not be modified:

- `message.id` (Anthropic message ID)
- `requestId` (Anthropic request ID)
- `signature` in thinking blocks
- `tool_use.id` (tool invocation ID)

These are left untouched. Only the session-local identifiers (`sessionId`, `uuid`, `parentUuid`, `agentId`, `cwd`) are regenerated.

### Restoring After Import

If an import causes problems:

```bash
ccsession restore           # Show snapshot info
ccsession restore --restore # Restore pre-import state
```

Restore requires typing "RESTORE" to confirm. The `--yes` flag bypasses this for automation.

## Installation

```bash
cd ccsession
pip install -e .
```

## Usage

### Global Flags

All subcommands support `--quiet` (`-q`) and `--verbose` (`-v`):

```bash
# Suppress informational output (errors and success only)
ccsession --quiet export --export-name my-session

# Show detailed output (file listings, debug info)
ccsession --verbose export --export-name my-session
```

### Export

```bash
# Portable export to .claude-sessions/ (default)
ccsession export --export-name feature-work

# Classic export to ~/claude_sessions/exports/
ccsession export --mode classic

# Export any historical session by ID (searches all projects)
ccsession export --session-id f33cdb42-0a41-40d4-91eb-c89c109af38a

# Custom output directory
ccsession export --output-dir /path/to/output --export-name my-session
```

### Import

```bash
# Import from local export
ccsession import .claude-sessions/my-session/

# Import into a different project directory
ccsession import .claude-sessions/my-session/ --project-path /path/to/project

# Keep original session ID (fails on conflict)
ccsession import .claude-sessions/my-session/ --preserve-session-id

# Skip config file import
ccsession import .claude-sessions/my-session/ --skip-config

# Skip auxiliary files (file-history, todos, plans)
ccsession import .claude-sessions/my-session/ --skip-auxiliary

# Non-interactive mode
ccsession import .claude-sessions/my-session/ --non-interactive
```

### Restore

```bash
# Show snapshot info
ccsession restore

# Restore pre-import state (requires confirmation)
ccsession restore --restore

# Skip confirmation (for automation)
ccsession restore --restore --yes
```

### Slash Commands

If installed to `~/.claude/commands/`:

```
/export-session [name]    # Portable export
/import-session <path>    # Import
/restore-backup           # Restore from snapshot
```

## How It Works

### Session Detection

When `--session-id` is provided, ccsession searches across **all projects** in `~/.claude/projects/` for a matching session file (exact or prefix match). This allows exporting any historical session from any directory.

Without `--session-id`, ccsession identifies the correct session for the current project by:

1. Finding all `.jsonl` files in the project's Claude storage directory
2. Filtering to sessions modified within the last 300 seconds
3. If running inside Claude Code, correlating the parent PID with session activity
4. Falling back to the most recently modified session

### Path Normalization

Claude Code normalizes project paths for storage:

| Character | Replacement |
|-----------|-------------|
| `/` | `-` |
| `\` | `-` |
| `:` | `-` |
| `.` | `-` |
| `_` | `-` |

Unix paths are prefixed with `-`. Windows paths are not.

Examples:
- `/mnt/c/python/my_project` becomes `-mnt-c-python-my-project`
- `C:\Users\dev\project` becomes `C-Users-dev-project`

ccsession replicates this normalization to locate and import sessions correctly.

### Output Formats

| Format | File | Description |
|--------|------|-------------|
| JSONL | `session/main.jsonl` | Original session data, one JSON object per line |
| Markdown | `RENDERED.md` | Human-readable conversation with collapsible thinking blocks |
| XML | `conversation_full.xml` | Structured format with UUID hierarchy and token usage |
| Trajectory | `trajectory.json` | Clean JSON for analysis with linked tool calls and statistics |
| Manifest | `.ccsession-manifest.json` | Session metadata, file inventory, environment context |

## File Locations

| Path | Purpose |
|------|---------|
| `~/.claude/projects/<path>/` | Claude Code session storage |
| `~/claude_sessions/exports/` | Classic export destination |
| `.claude-sessions/` | Portable export destination (default) |
| `~/.claude-session-imports/` | Import logs and snapshots |
| `~/.claude/commands/` | User slash commands |

## Project Structure

```
ccsession/
├── pyproject.toml               # Package metadata and entry point
├── ccsession/                     # Main package
│   ├── __init__.py              # Version constant
│   ├── __main__.py              # python -m ccsession entry point
│   ├── cli.py                   # CLI (export, import, restore)
│   ├── constants.py             # Named constants
│   ├── output.py               # Verbosity-aware output (info, detail, error, success)
│   ├── paths.py                 # Claude Code path helpers
│   ├── utils.py                 # Shared utilities (timestamps, JSON I/O)
│   ├── restore.py               # Restore logic
│   ├── export/                  # Export subpackage
│   │   ├── session_discovery.py # Session detection and selection
│   │   ├── parsers.py           # JSONL parsing and metadata extraction
│   │   ├── formatters.py        # Markdown and XML formatting
│   │   ├── collectors.py        # Session data and config collection
│   │   ├── manifest.py          # Manifest and RENDERED.md generation
│   │   ├── trajectory.py        # Trajectory JSON formatter
│   │   └── exporter.py          # Export orchestration
│   └── importing/               # Import subpackage
│       ├── validation.py        # Manifest and version validation
│       ├── uuids.py             # UUID and agent ID generation
│       ├── snapshot.py          # Pre-import backup
│       ├── session_io.py        # JSONL read/write
│       ├── auxiliary.py         # File history, todos, plan import
│       ├── config.py            # Config file import
│       ├── import_log.py        # Import logging
│       └── importer.py          # Import orchestration
└── tests/                       # 128 tests
```

## Limitations

- Sessions are one-way portable: you can export and import, but there's no merge or sync
- File-history snapshots reference files by content hash; the original paths are not preserved
- Import generates new UUIDs, so the imported session is a copy, not the original
- Large sessions (500+ messages) produce large RENDERED.md files that may be slow to render on GitHub

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

128 tests covering manifest validation, UUID regeneration, path normalization, session I/O, restore functionality, trajectory transformation, CLI flags, and cross-project session lookup.

## Acknowledgments

This project is based on [cctrace](https://github.com/jimmc414/cctrace) by [@jimmc414](https://github.com/jimmc414). Thanks for the original work on Claude Code session export tooling.

## License

MIT
