"""Tests for `scripts/install.sh`: installing jiyuu with uv into a temporary folder, running
the installed command, and removing it again.

Skipped where `uv` or `bash` is not available. The first run on a machine downloads
jiyuu's dependencies into uv's cache; later runs take a few seconds.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parent.parent
SCRIPT = REPOSITORY / "scripts" / "install.sh"
FIXTURE = REPOSITORY / "tests" / "data" / "ink" / "worked-example.ink"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("bash") is None, reason="needs uv and bash"
)


def _run(*args: str | Path, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(arg) for arg in args], env=env, cwd=cwd, capture_output=True, text=True, check=False)


def test_install_run_and_uninstall(tmp_path: Path) -> None:
    """The script installs a `jiyuu` that runs from another folder, with `jiyuu <file>`
    meaning `jiyuu open <file>` and the other commands by name; `--uninstall` removes it."""
    env = dict(os.environ, UV_TOOL_DIR=str(tmp_path / "tools"), UV_TOOL_BIN_DIR=str(tmp_path / "bin"))
    jiyuu = tmp_path / "bin" / "jiyuu"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    installed = _run(SCRIPT, "--no-client", env=env, cwd=elsewhere)
    assert installed.returncode == 0, installed.stderr
    assert jiyuu.exists()

    version = _run(jiyuu, "version", env=env, cwd=elsewhere)
    assert version.returncode == 0 and version.stdout.strip() == "0.1.0"
    assert _run(jiyuu, "check", FIXTURE, env=env, cwd=elsewhere).returncode == 0
    exported = _run(jiyuu, "export", "--mm", FIXTURE, "map.mm", env=env, cwd=elsewhere)
    assert exported.returncode == 0, exported.stderr
    assert 'TEXT="Project"' in (elsewhere / "map.mm").read_text(encoding="utf-8")

    # A first argument that is neither a command nor an existing file shows the help.
    missing = _run(jiyuu, "missing.ink", env=env, cwd=elsewhere)
    assert missing.returncode == 2 and "missing.ink" in missing.stderr and "Commands" in missing.stdout

    removed = _run(SCRIPT, "--uninstall", env=env, cwd=elsewhere)
    assert removed.returncode == 0, removed.stderr
    assert not jiyuu.exists()
    again = _run(SCRIPT, "--uninstall", env=env, cwd=elsewhere)
    assert again.returncode == 0 and "nothing to remove" in again.stdout
