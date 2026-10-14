"""Exercise live-run cleanup with a fake Claude executable; no account usage."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'e2e_live.sh'


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('bash') or not shutil.which('git'),
                    reason='the live helper requires a POSIX shell and git')
def test_relative_config_uses_one_absolute_store_and_restores_import_storage(tmp_path):
    # Apostrophes also exercise cleanup's safe passing of project paths to Python.
    work = tmp_path / "working'directory"
    work.mkdir()
    temporary = work / 'temp'
    temporary.mkdir()
    store = work / 'relative-claude'
    storage = store / 'ccsession-imports'
    storage.mkdir(parents=True)
    (storage / 'keep.txt').write_bytes(b'original snapshot')
    bin_dir = work / 'bin'
    bin_dir.mkdir()
    fake_claude = bin_dir / 'claude'
    fake_claude.write_text('#!/usr/bin/env python3\nimport os\nfrom pathlib import Path\n'
                          'Path(os.environ["CCSESSION_TEST_LOG"]).write_text(os.environ["CLAUDE_CONFIG_DIR"])\n'
                          'raise SystemExit(1)\n', encoding='utf-8')
    fake_claude.chmod(0o755)
    log = work / 'called-config.txt'
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
               CLAUDE_CONFIG_DIR='relative-claude', TMPDIR=str(temporary), CCSESSION_TEST_LOG=str(log))
    env.pop('CLAUDE_CODE_PROJECT_DIR_NAME', None)

    result = subprocess.run(['bash', str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 1, result.stderr
    assert Path(log.read_text()).resolve() == store.resolve()
    assert (storage / 'keep.txt').read_bytes() == b'original snapshot'
    assert not list(temporary.glob('ccsession-e2e.*'))
    assert not list(store.glob('ccsession-imports.e2e-*'))
