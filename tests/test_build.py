"""Tests for scripts/build.py, through its CLI, on a temp copy of the repo."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PROCESS = "# Okeanos\n\nTexto neutro do processo.\n"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "build.py", tmp_path / "scripts" / "build.py")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "process.md").write_text(PROCESS, encoding="utf-8")
    return tmp_path


def run(repo, *args):
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "build.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_build_writes_claude_output_style_from_process(repo):
    result = run(repo)

    assert result.returncode == 0, result.stderr
    style = (repo / "output-styles" / "okeanos.md").read_text(encoding="utf-8")
    assert style == (
        "---\n"
        "name: okeanos\n"
        "description: Fluxo contínuo de desenvolvimento. Classifica cada demanda"
        " e conduz pelo processo, com dois gates de aprovação.\n"
        "keep-coding-instructions: true\n"
        "force-for-plugin: true\n"
        "---\n"
        "\n" + PROCESS
    )


def test_build_writes_agents_md_block_from_process(repo):
    result = run(repo)

    assert result.returncode == 0, result.stderr
    block = (repo / "adapters" / "agents-md" / "okeanos.md").read_text(encoding="utf-8")
    lines = block.splitlines()
    assert lines[0] == "<!-- okeanos:start -->"
    assert lines[-1] == "<!-- okeanos:end -->"
    assert "gerado" in lines[1] and "core/process.md" in lines[1]
    assert PROCESS in block
