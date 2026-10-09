"""When the git dir is read-only (Codex's workspace-write sandbox), session state and
metrics fall back to a writable dir under TMPDIR, so the definition of done keeps working.
Approvals stay in the git dir: the human writes them from outside the sandbox."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "hooks" / "okeanos.py"
OKEANOS = Path(__file__).resolve().parent.parent / "bin" / "okeanos"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def readonly_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "docs" / "agents").mkdir(parents=True)
    (root / "docs" / "agents" / "checks.json").write_text(json.dumps(
        {"onDone": [{"name": "test", "cmd": "test -f ok.flag"}]}))
    (root / "app.py").write_text("x = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    gitdir = root / ".git"
    original = gitdir.stat().st_mode
    gitdir.chmod(original & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    yield root
    gitdir.chmod(original)


def hook(event, payload, tmpdir, agent="codex"):
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    env.pop("OKEANOS_HOOK_DEBUG", None)
    p = subprocess.run([sys.executable, str(ENGINE), "--agent", agent, event], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=120, cwd=str(tmpdir))
    out = p.stdout.strip()
    return json.loads(out) if out else None


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_definition_of_done_still_blocks_when_git_dir_is_read_only(readonly_repo, tmp_path):
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    base = {"session_id": "ro1", "cwd": str(readonly_repo)}
    hook("session-start", {**base, "hook_event_name": "SessionStart", "source": "startup"}, tmpdir)
    (readonly_repo / "app.py").write_text("x = 2\n")
    out = hook("stop", {**base, "hook_event_name": "Stop", "stop_hook_active": False,
                        "last_assistant_message": "pronto"}, tmpdir)
    assert out is not None and out.get("decision") == "block", out
    assert not (readonly_repo / ".git" / "okeanos").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_metrics_land_in_the_fallback_and_okeanos_metrics_reads_them(readonly_repo, tmp_path):
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    base = {"session_id": "ro2", "cwd": str(readonly_repo)}
    hook("session-start", {**base, "hook_event_name": "SessionStart", "source": "startup"}, tmpdir)
    (readonly_repo / "app.py").write_text("x = 3\n")
    hook("stop", {**base, "hook_event_name": "Stop", "stop_hook_active": False,
                  "last_assistant_message": "pronto"}, tmpdir)
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    p = subprocess.run([str(OKEANOS), "metrics", "1"], cwd=readonly_repo, capture_output=True, text=True, env=env)
    assert "stop:block" in p.stdout, p.stdout + p.stderr
