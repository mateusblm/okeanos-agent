"""The user CLI `okeanos` (bin/okeanos), driven as a subprocess.

Approvals need a real terminal, so the success path runs under a pseudo-TTY;
the refusal path runs with plain pipes, as an agent would. Time is pinned with
OKEANOS_NOW (seconds since the epoch). Every run uses a throwaway repo as cwd.
"""

import json
import os
import pty
import select
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "bin" / "okeanos"
NOW = 1_800_000_000


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text("def test_add():\n    assert 1 + 1 == 2\n")
    git(root, "init", "-q", "-b", "feature")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


AGENT_VARS = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI", "CODEX_SANDBOX",
              "CODEX_SANDBOX_NETWORK_DISABLED", "CURSOR_AGENT")


def env_with(now=NOW, path=None, extra=None):
    """The user's own terminal: no agent-session variables (these tests may run inside an agent)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OKEANOS_") and k not in AGENT_VARS}
    env["OKEANOS_NOW"] = str(now)
    env.update(extra or {})
    if path is not None:
        env["PATH"] = path
    return env


def run(cwd, *args, now=NOW, path=None):
    """Plain pipes: stdin and stdout are not a TTY."""
    p = subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, capture_output=True, text=True,
                       env=env_with(now, path), stdin=subprocess.DEVNULL, timeout=60)
    return p.returncode, p.stdout + p.stderr


def run_tty(cwd, *args, now=NOW, extra=None):
    """stdin and stdout on a pseudo-terminal, as in the user's own terminal."""
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, str(CLI), *args], cwd=cwd, env=env_with(now, extra=extra),
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    chunks = []
    while True:
        ready, _, _ = select.select([master], [], [], 30)
        if not ready:
            break
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(master)
    return p.wait(timeout=30), b"".join(chunks).decode(errors="replace")


def approvals_file(root):
    return root / ".git" / "okeanos" / "approvals.json"


# ---------------------------------------------------------------------------
# aprovar
# ---------------------------------------------------------------------------

def test_approve_in_a_terminal_records_the_target_for_ten_minutes(repo):
    code, out = run_tty(repo, "aprovar", "tests/test_calc.py")
    assert code == 0, out
    assert "tests/test_calc.py" in out
    data = json.loads(approvals_file(repo).read_text())
    assert data["tests/test_calc.py"]["expires_at"] == NOW + 600


def test_approve_prints_until_when(repo):
    code, out = run_tty(repo, "aprovar", "push")
    assert code == 0 and "push" in out and "até" in out


def test_approve_without_a_terminal_is_refused(repo):
    code, out = run(repo, "aprovar", "push")
    assert code != 0
    assert "terminal" in out
    assert not approvals_file(repo).exists()


@pytest.mark.parametrize("var", AGENT_VARS)
@pytest.mark.parametrize("sub", [["aprovar", "push"], ["revogar"]])
def test_approve_inside_an_agent_session_is_refused_even_with_a_terminal(repo, var, sub):
    code, out = run_tty(repo, *sub, extra={var: "1"})
    assert code != 0
    assert var in out
    assert not approvals_file(repo).exists()


def test_approve_from_a_subdirectory_stores_a_repo_relative_path(repo):
    code, out = run_tty(repo / "tests", "aprovar", "test_calc.py")
    assert code == 0, out
    assert "tests/test_calc.py" in json.loads(approvals_file(repo).read_text())


def test_approve_a_package(repo):
    code, out = run_tty(repo, "aprovar", "pacote:expresss")
    assert code == 0, out
    assert "pacote:expresss" in json.loads(approvals_file(repo).read_text())


@pytest.mark.parametrize("target", ["src/nao_existe.py", "../fora.py", "pacote:", "force-push"])
def test_approve_refuses_unknown_targets(repo, target):
    code, out = run_tty(repo, "aprovar", target)
    assert code != 0
    assert not approvals_file(repo).exists()


def test_approve_outside_a_repo_is_refused(tmp_path):
    code, out = run_tty(tmp_path, "aprovar", "push")
    assert code != 0


# ---------------------------------------------------------------------------
# aprovacoes / revogar
# ---------------------------------------------------------------------------

def test_list_shows_only_live_approvals(repo):
    run_tty(repo, "aprovar", "push", now=NOW)
    run_tty(repo, "aprovar", "tests/test_calc.py", now=NOW + 500)
    code, out = run(repo, "aprovacoes", now=NOW + 700)
    assert code == 0
    assert "tests/test_calc.py" in out and "push" not in out


def test_list_without_approvals_says_so(repo):
    code, out = run(repo, "aprovacoes")
    assert code == 0 and "Nenhuma" in out


def test_revoke_one_target(repo):
    run_tty(repo, "aprovar", "push")
    run_tty(repo, "aprovar", "tests/test_calc.py")
    code, _ = run_tty(repo, "revogar", "push")
    assert code == 0
    assert set(json.loads(approvals_file(repo).read_text())) == {"tests/test_calc.py"}


def test_revoke_all(repo):
    run_tty(repo, "aprovar", "push")
    run_tty(repo, "aprovar", "tests/test_calc.py")
    code, _ = run_tty(repo, "revogar")
    assert code == 0
    assert json.loads(approvals_file(repo).read_text()) == {}


# ---------------------------------------------------------------------------
# metrics, githooks, doctor, help
# ---------------------------------------------------------------------------

def write_metrics(root, events):
    d = root / ".git" / "okeanos"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def test_metrics_counts_kinds_and_breaks_down_by_agent(repo):
    write_metrics(repo, [
        {"ts": NOW - 10, "agent": "claude", "session": "a", "kind": "pre-bash:ask"},
        {"ts": NOW - 10, "agent": "claude", "session": "a", "kind": "stop:pass"},
        {"ts": NOW - 10, "agent": "codex", "session": "b", "kind": "pre-bash:ask"},
        {"ts": NOW - 40 * 86400, "agent": "codex", "session": "c", "kind": "stop:block"},
    ])
    code, out = run(repo, "metrics", "30")
    assert code == 0
    assert "2 sessões" in out
    assert "    2  pre-bash:ask" in out and "stop:block" not in out
    assert "Por agente" in out
    assert "    2  claude" in out and "    1  codex" in out


def test_metrics_without_data(repo):
    code, out = run(repo, "metrics")
    assert code == 0 and "Sem métricas" in out


def test_doctor_reports_repo_and_agents(repo, tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    for name in ("codex", "git"):
        target = fake_bin / name
        if name == "git":
            target.symlink_to(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
        else:
            target.write_text("#!/bin/sh\n")
            target.chmod(0o755)
    (repo / "AGENTS.md").write_text("x")
    run_tty(repo, "aprovar", "push")
    code, out = run(repo, "doctor", path=str(fake_bin))
    assert code == 0
    assert str(CLI.parent.parent) in out
    assert sys.version.split()[0] in out
    assert "AGENTS.md" in out and "checks.json" in out
    assert "push" in out
    assert "codex" in out
    lines = {l.strip() for l in out.splitlines()}
    assert any(l.startswith("codex") and "/fakebin/codex" in l for l in lines)
    assert any(l.startswith("claude") and "não" in l for l in lines)


def test_help_lists_subcommands(repo):
    code, out = run(repo, "--help")
    assert code == 0
    for sub in ("aprovar", "aprovacoes", "revogar", "metrics", "githooks", "doctor"):
        assert sub in out


def test_unknown_subcommand_fails(repo):
    code, _ = run(repo, "voar")
    assert code != 0
