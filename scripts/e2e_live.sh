#!/usr/bin/env bash
# Live end-to-end check for ccsession against the installed Claude Code CLI.
#
#   scripts/e2e_live.sh [--keep] [--model <model>]
#   env: CCSESSION_E2E_MODEL (default sonnet), CCSESSION_E2E_PROMPT (default: fix-the-bug task)
#
# 1. creates a throwaway Python project with a failing test,
# 2. has `claude -p` fix it (one Explore sub-agent, an Edit and a Write),
# 3. exports that session with ccsession, imports it into a second project,
# 4. resumes the imported session with `claude -p --resume` and checks the answer.
#
# Requires a logged-in `claude` CLI and spends API usage. Works against the real
# config dir (CLAUDE_CONFIG_DIR or ~/.claude); everything it creates is removed
# unless --keep is given. ccsession's import storage (the single pre-import
# snapshot slot and the import index) is saved when the run starts and put back
# however it ends, so the run never replaces the snapshot of a real import.
set -euo pipefail

KEEP=0
MODEL=${CCSESSION_E2E_MODEL:-sonnet}
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP=1 ;;
    --model) MODEL=$2; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v claude >/dev/null || { echo "claude CLI not found on PATH" >&2; exit 2; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
# Resolve symlinks (macOS /var -> /private/var): Claude Code records the real path.
WORK_TMP=$(mktemp -d "${TMPDIR:-/tmp}/ccsession-e2e.XXXXXX") || { echo "mktemp failed" >&2; exit 2; }
WORK=$(cd "$WORK_TMP" && pwd -P)
case "$WORK" in "${TMPDIR:-/tmp}"*|/tmp/*|/private/*|/var/*) ;; *) echo "unexpected work dir: $WORK" >&2; exit 2 ;; esac
CLAUDE_DIR=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
export PYTHONPATH=$REPO${PYTHONPATH:+:$PYTHONPATH}
# The session id is chosen up front so cleanup can find the session even when
# `claude -p` fails or is interrupted after writing it.
SID=$(python3 -c 'import uuid; print(uuid.uuid4())')
NEW_SID=""
# Mirrors ccsession.paths.get_import_storage_dir
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
  IMPORT_STORAGE=$CLAUDE_DIR/ccsession-imports
else
  IMPORT_STORAGE=$HOME/.claude-session-imports
fi
IMPORT_STORAGE_BACKUP=""
IMPORT_STORAGE_PARTIAL=""
IMPORT_STORAGE_SAVED=0

# Called right after the EXIT trap is armed. The storage counts as saved only once
# the copy has completed (or the storage is known to be absent); a failed or
# interrupted copy leaves the real storage untouched. A symlinked storage is
# followed, so its contents, not the link, are saved. The copy sits next to the
# storage so putting it back is a rename; -p keeps the mtimes the restore plan
# compares.
save_import_storage() {
  if [ -L "$IMPORT_STORAGE" ]; then
    IMPORT_STORAGE=$(cd "$IMPORT_STORAGE" && pwd -P)
  fi
  if [ -e "$IMPORT_STORAGE" ]; then
    IMPORT_STORAGE_PARTIAL="$IMPORT_STORAGE.e2e-backup.$$"
    rm -rf "$IMPORT_STORAGE_PARTIAL"
    cp -Rp "$IMPORT_STORAGE" "$IMPORT_STORAGE_PARTIAL"
    IMPORT_STORAGE_BACKUP=$IMPORT_STORAGE_PARTIAL
    IMPORT_STORAGE_PARTIAL=""
  fi
  IMPORT_STORAGE_SAVED=1
}

restore_import_storage() {
  if [ "$IMPORT_STORAGE_SAVED" != 1 ]; then
    # The save never completed: the real storage was not touched, drop the partial copy
    [ -z "$IMPORT_STORAGE_PARTIAL" ] || rm -rf "$IMPORT_STORAGE_PARTIAL"
    return 0
  fi
  local discard="$IMPORT_STORAGE.e2e-discard.$$"
  rm -rf "$discard"
  [ ! -e "$IMPORT_STORAGE" ] || mv "$IMPORT_STORAGE" "$discard"
  if [ -n "$IMPORT_STORAGE_BACKUP" ]; then
    mv "$IMPORT_STORAGE_BACKUP" "$IMPORT_STORAGE"
    IMPORT_STORAGE_BACKUP=""
  fi
  rm -rf "$discard"
  IMPORT_STORAGE_SAVED=0
}

# Drop the prompt-history lines of the sessions this run created, if Claude Code
# or the import recorded any; other sessions' lines, the file's permissions and a
# symlink to it are kept.
remove_history_lines() {
  [ -f "$CLAUDE_DIR/history.jsonl" ] || return 0
  python3 - "$CLAUDE_DIR/history.jsonl" "$@" <<'PYEOF'
import json, sys
from ccsession.history_file import rewrite_lines
path, ids = sys.argv[1], set(a for a in sys.argv[2:] if a)

def keep(lines):
    kept = []
    for line in lines:
        try:
            rec = json.loads(line)
        except (ValueError, RecursionError):
            rec = None
        if not (isinstance(rec, dict) and rec.get('sessionId') in ids):
            kept.append(line)
    return kept

if ids:
    rewrite_lines(path, keep)
PYEOF
}

cleanup() {
  # The import prints its new id before writing anything; recover it if the run
  # stopped before the id was parsed below.
  if [ -z "$NEW_SID" ] && [ -f "${IMPORT_LOG:-}" ]; then
    NEW_SID=$(sed -n 's/.*Importing as session: \([0-9a-f-]\{36\}\).*/\1/p' "$IMPORT_LOG" | head -1)
  fi
  restore_import_storage
  remove_history_lines "$SID" "$NEW_SID"
  if [ "$KEEP" = 1 ]; then
    echo "kept: $WORK"
    return
  fi
  for p in "$WORK/proj" "$WORK/proj2"; do
    norm=$(python3 -c "from ccsession.paths import get_normalized_project_dir as n; print(n('$p'))")
    rm -rf "$CLAUDE_DIR/projects/$norm"
  done
  for sid in $SID $NEW_SID; do
    # The sessions themselves, wherever they landed (CLAUDE_CODE_PROJECT_DIR_NAME puts
    # them in a shared directory that must not be removed as a whole)
    rm -rf "$CLAUDE_DIR"/projects/*/"$sid.jsonl" "$CLAUDE_DIR"/projects/*/"$sid"
    rm -rf "$CLAUDE_DIR/file-history/$sid" "$CLAUDE_DIR/session-env/$sid"
  done
  rm -rf "$WORK"
}
trap cleanup EXIT
save_import_storage

echo "== fixture project"
mkdir -p "$WORK/proj/calc" "$WORK/proj/tests"
cat > "$WORK/proj/calc/__init__.py" <<'PY'
from calc.ops import average, total
PY
cat > "$WORK/proj/calc/ops.py" <<'PY'
def total(values):
    return sum(values)


def average(values):
    if not values:
        raise ValueError("average of empty list")
    return sum(values) / len(values) + 1
PY
cat > "$WORK/proj/tests/test_ops.py" <<'PY'
from calc import average, total


def test_total():
    assert total([1, 2, 3]) == 6


def test_average():
    assert average([2, 4, 6]) == 4
PY
git -C "$WORK/proj" init -q
git -C "$WORK/proj" add -A
git -C "$WORK/proj" -c user.email=e2e@example.com -c user.name=e2e commit -qm fixture

echo "== real task with claude -p ($MODEL)"
DEFAULT_PROMPT='This Python project has one failing test. 1) Use the Agent tool to launch an Explore subagent that reports which function is buggy. 2) Run: python3 -m pytest -q. 3) Fix the bug in calc/ops.py with the Edit tool. 4) Create CHANGELOG.md with the Write tool describing the fix in two lines. 5) Run the tests again. 6) Reply with a one-line summary.'
# CCSESSION_E2E_PROMPT overrides the task, e.g. to force a background sub-agent.
PROMPT=${CCSESSION_E2E_PROMPT:-$DEFAULT_PROMPT}
RUN=$(cd "$WORK/proj" && claude -p "$PROMPT" --session-id "$SID" --model "$MODEL" --permission-mode acceptEdits \
  --allowedTools "Read,Edit,Write,Glob,Grep,Agent,Bash(python3:*),Bash(ls:*),Bash(cat:*)" \
  --max-turns 40 --output-format json < /dev/null)
printf '%s' "$RUN" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not d.get("is_error"), d.get("result"); assert d["session_id"] == sys.argv[1], d["session_id"]' "$SID"
(cd "$WORK/proj" && python3 -m pytest -q >/dev/null) || { echo "fixture tests still failing after the task" >&2; exit 1; }
echo "   session $SID"

echo "== export"
(cd "$WORK/proj" && python3 -m ccsession --quiet export --session-id "$SID" --output-dir "$WORK/exports" --export-name live)
python3 - "$WORK/exports/live" <<'PY'
import json, sys
from pathlib import Path
m = json.loads((Path(sys.argv[1]) / ".ccsession-manifest.json").read_text())
assert m["layout_version"] == 2, m
assert m["session_data"]["agent_sessions"], "expected at least one sub-agent transcript"
print(f"   {len(m['session_data']['agent_sessions'])} sub-agent(s), claude code {m['claude_code_version']}")
PY

echo "== import into a second project"
cp -R "$WORK/proj" "$WORK/proj2"
rm -rf "$WORK/proj2/.claude-sessions"
IMPORT_LOG=$WORK/import.log
(cd "$WORK/proj2" && python3 -m ccsession import "$WORK/exports/live" --project-path "$WORK/proj2" --non-interactive) | tee "$IMPORT_LOG"
NEW_SID=$(sed -n 's/.*Importing as session: \([0-9a-f-]\{36\}\).*/\1/p' "$IMPORT_LOG")
[ -n "$NEW_SID" ] || { echo "import did not report a session id" >&2; exit 1; }

echo "== resume with the real CLI"
ANSWER=$(cd "$WORK/proj2" && claude -p --resume "$NEW_SID" --model "$MODEL" --max-turns 1 --output-format json \
  "Do not use any tools. In one sentence: what bug did you fix earlier in this conversation and what new file did you create?" < /dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not d.get("is_error"), d.get("result"); print(d["result"])')
echo "   $ANSWER"
printf '%s' "$ANSWER" | grep -qi "average" || { echo "resumed session did not recall the fix" >&2; exit 1; }
printf '%s' "$ANSWER" | grep -qi "changelog" || { echo "resumed session did not recall the new file" >&2; exit 1; }
echo "== PASS"
