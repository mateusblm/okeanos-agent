"""`okeanos githooks`: per-project git hooks, driven with real `git commit` and `git push`.

Every repo is a throwaway under tmp_path (pushes go to a local bare repo), every
command runs with cwd pinned there, and GIT_* variables are stripped so nothing
reaches the repository running these tests. Only the CLI, git and files on disk
are observed; engine internals are never imported.
"""

import json
import os
import pty
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
CLI = PLUGIN / "bin" / "okeanos"
NOW = 1_800_000_000
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"

TEST_FILE = """from src.calc import add


def test_add():
    assert add(1, 2) == 3


def test_add_negative():
    assert add(-1, -2) == -3
"""


def clean_env(extra=None, path=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OKEANOS_", "GIT_"))}
    env["OKEANOS_NOW"] = str(NOW)
    if path is not None:
        env["PATH"] = path
    env.update(extra or {})
    return env


def git(cwd, *args, check=True, env=None):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env or clean_env(),
                       stdin=subprocess.DEVNULL, timeout=120)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{p.stdout}{p.stderr}")
    return p


def okeanos(cwd, *args, cli=CLI):
    p = subprocess.run([sys.executable, str(cli), *args], cwd=cwd, capture_output=True, text=True,
                       env=clean_env(), stdin=subprocess.DEVNULL, timeout=60)
    return p.returncode, p.stdout + p.stderr


def approve(cwd, target):
    """`okeanos aprovar` under a pseudo-terminal, as the human would."""
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, str(CLI), "aprovar", target], cwd=cwd, env=clean_env(),
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    while True:
        ready, _, _ = select.select([master], [], [], 30)
        if not ready:
            break
        try:
            if not os.read(master, 4096):
                break
        except OSError:
            break
    os.close(master)
    assert p.wait(timeout=30) == 0


def commit(root, message="change", env=None):
    git(root, "add", "-A", env=env)
    p = git(root, "commit", "-q", "-m", message, check=False, env=env)
    return p.returncode, p.stdout + p.stderr


def head(root):
    return git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "tests" / "test_calc.py").write_text(TEST_FILE)
    git(root, "init", "-q", "-b", "feature")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    commit(root, "init")
    return root


@pytest.fixture
def installed(repo):
    code, out = okeanos(repo, "githooks")
    assert code == 0, out
    return repo


def hooks_dir(root):
    return root / ".git" / "hooks"


def snapshot(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in sorted(directory.iterdir()) if p.is_file()}


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------

def test_install_writes_executable_pre_commit_and_pre_push(installed):
    for name in ("pre-commit", "pre-push"):
        hook = hooks_dir(installed) / name
        assert hook.exists() and os.access(hook, os.X_OK)
        assert str(CLI.resolve()) in hook.read_text()


def test_install_outside_a_repo_fails(tmp_path):
    code, out = okeanos(tmp_path, "githooks")
    assert code != 0 and "git" in out


def test_install_is_idempotent(installed):
    before = snapshot(hooks_dir(installed))
    code, out = okeanos(installed, "githooks")
    assert code == 0, out
    assert snapshot(hooks_dir(installed)) == before


def test_install_respects_core_hooks_path(repo):
    git(repo, "config", "core.hooksPath", ".githooks")
    code, out = okeanos(repo / "src", "githooks")
    assert code == 0, out
    assert (repo / ".githooks" / "pre-commit").exists()
    assert not (hooks_dir(repo) / "pre-commit").exists()
    (repo / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, _ = commit(repo)
    assert code != 0


def test_install_from_a_worktree_uses_the_common_hooks_dir(repo, tmp_path):
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "other", str(wt))
    code, out = okeanos(wt, "githooks")
    assert code == 0, out
    assert (hooks_dir(repo) / "pre-commit").exists()
    (wt / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, _ = commit(wt)
    assert code != 0


def test_existing_hook_is_preserved_and_runs_first(repo, tmp_path):
    marker = tmp_path / "ran"
    own = hooks_dir(repo) / "pre-commit"
    own.write_text(f"#!/bin/sh\necho mine >> '{marker}'\nexit 0\n")
    own.chmod(0o755)
    code, out = okeanos(repo, "githooks")
    assert code == 0, out
    assert (hooks_dir(repo) / "pre-commit.okeanos-prev").read_text().startswith("#!/bin/sh\necho mine")
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n")
    code, out = commit(repo)
    assert code == 0, out
    assert marker.read_text() == "mine\n"


def test_failing_existing_hook_fails_the_commit(repo):
    own = hooks_dir(repo) / "pre-commit"
    own.write_text("#!/bin/sh\necho 'own hook says no' >&2\nexit 1\n")
    own.chmod(0o755)
    okeanos(repo, "githooks")
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n")
    before = head(repo)
    code, out = commit(repo)
    assert code != 0 and "own hook says no" in out
    assert head(repo) == before


def test_existing_pre_push_hook_still_gets_the_refs_on_stdin(repo, tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    got = tmp_path / "stdin"
    own = hooks_dir(repo) / "pre-push"
    own.write_text(f"#!/bin/sh\ncat > '{got}'\n")
    own.chmod(0o755)
    okeanos(repo, "githooks")
    p = git(repo, "push", "-q", "origin", "feature", check=False)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "refs/heads/feature" in got.read_text()


def test_reinstall_with_existing_hook_does_not_nest_it(repo):
    own = hooks_dir(repo) / "pre-commit"
    own.write_text("#!/bin/sh\nexit 0\n")
    own.chmod(0o755)
    okeanos(repo, "githooks")
    before = snapshot(hooks_dir(repo))
    okeanos(repo, "githooks")
    assert snapshot(hooks_dir(repo)) == before
    assert not (hooks_dir(repo) / "pre-commit.okeanos-prev.okeanos-prev").exists()


def test_uninstall_removes_okeanos_hooks_and_restores_the_previous_ones(repo):
    own = hooks_dir(repo) / "pre-commit"
    original = "#!/bin/sh\nexit 0\n"
    own.write_text(original)
    own.chmod(0o755)
    okeanos(repo, "githooks")
    code, out = okeanos(repo, "githooks", "--uninstall")
    assert code == 0, out
    assert own.read_text() == original and os.access(own, os.X_OK)
    assert not (hooks_dir(repo) / "pre-commit.okeanos-prev").exists()
    assert not (hooks_dir(repo) / "pre-push").exists()
    (repo / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, out = commit(repo)
    assert code == 0, out


def test_uninstall_leaves_foreign_hooks_alone(repo):
    own = hooks_dir(repo) / "pre-push"
    own.write_text("#!/bin/sh\nexit 0\n")
    own.chmod(0o755)
    code, out = okeanos(repo, "githooks", "--uninstall")
    assert code == 0, out
    assert own.read_text() == "#!/bin/sh\nexit 0\n"


# ---------------------------------------------------------------------------
# pre-commit: secrets
# ---------------------------------------------------------------------------

def test_secret_blocks_the_commit_showing_file_and_type_only(installed):
    (installed / "src" / "config.py").write_text(f'KEY = "{AWS_KEY}"\n')
    before = head(installed)
    code, out = commit(installed)
    assert code != 0
    assert "src/config.py" in out and "AWS access key" in out
    assert AWS_KEY not in out
    assert head(installed) == before


def test_only_staged_content_is_scanned(installed):
    (installed / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n")
    git(installed, "add", "src/calc.py")
    (installed / "unstaged.py").write_text(f'KEY = "{AWS_KEY}"\n')
    p = git(installed, "commit", "-q", "-m", "only calc", check=False)
    assert p.returncode == 0, p.stdout + p.stderr


def test_clean_commit_passes(installed):
    (installed / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n")
    code, out = commit(installed)
    assert code == 0, out


# ---------------------------------------------------------------------------
# pre-commit: committed tests are the contract
# ---------------------------------------------------------------------------

def test_removing_an_assertion_from_a_committed_test_blocks_the_commit(installed):
    (installed / "tests" / "test_calc.py").write_text(TEST_FILE.replace("    assert add(-1, -2) == -3\n", "    pass\n"))
    before = head(installed)
    code, out = commit(installed)
    assert code != 0
    assert "tests/test_calc.py" in out
    assert "Para aprovar: okeanos aprovar tests/test_calc.py" in out
    assert head(installed) == before


def test_altering_an_assertion_blocks_the_commit(installed):
    (installed / "tests" / "test_calc.py").write_text(TEST_FILE.replace("== 3", "== 4"))
    code, out = commit(installed)
    assert code != 0 and "okeanos aprovar tests/test_calc.py" in out


def test_deleting_a_committed_test_blocks_the_commit(installed):
    (installed / "tests" / "test_calc.py").unlink()
    code, out = commit(installed)
    assert code != 0 and "tests/test_calc.py" in out


def test_new_skip_marker_in_a_committed_test_blocks_the_commit(installed):
    skipped = TEST_FILE.replace("def test_add_negative", "@pytest.mark.skip\ndef test_add_negative")
    (installed / "tests" / "test_calc.py").write_text("import pytest\n" + skipped)
    code, out = commit(installed)
    assert code != 0 and "okeanos aprovar tests/test_calc.py" in out


def test_approved_test_change_passes(installed):
    approve(installed, "tests/test_calc.py")
    (installed / "tests" / "test_calc.py").write_text(TEST_FILE.replace("== 3", "== 4"))
    code, out = commit(installed)
    assert code == 0, out


def test_expired_approval_does_not_pass(installed):
    approve(installed, "tests/test_calc.py")
    (installed / "tests" / "test_calc.py").write_text(TEST_FILE.replace("== 3", "== 4"))
    code, _ = commit(installed, env=clean_env({"OKEANOS_NOW": str(NOW + 601)}))
    assert code != 0


def test_reformatting_a_committed_test_passes(installed):
    reformatted = TEST_FILE.replace("    assert add(1, 2) == 3\n", "    assert add(\n        1,\n        2,\n    ) == 3\n")
    (installed / "tests" / "test_calc.py").write_text(reformatted.replace("add(-1, -2)", "add(-1,-2)"))
    code, out = commit(installed)
    assert code == 0, out


def test_adding_tests_passes(installed):
    (installed / "tests" / "test_calc.py").write_text(TEST_FILE + "\n\ndef test_zero():\n    assert add(0, 0) == 0\n")
    (installed / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n")
    code, out = commit(installed)
    assert code == 0, out


def test_new_suppression_warns_but_passes(installed):
    (installed / "src" / "calc.py").write_text("def add(a, b):  # type: ignore\n    return a + b\n")
    code, out = commit(installed)
    assert code == 0, out
    assert "src/calc.py" in out and "supress" in out


# ---------------------------------------------------------------------------
# pre-push: onDone
# ---------------------------------------------------------------------------

@pytest.fixture
def remote(installed, tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(installed, "remote", "add", "origin", str(bare))
    return bare


def set_checks(root, checks):
    d = root / "docs" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "checks.json").write_text(json.dumps(checks))
    code, out = commit(root, "checks")
    assert code == 0, out


def push(root):
    p = git(root, "push", "-q", "origin", "feature", check=False)
    return p.returncode, p.stdout + p.stderr


def remote_has_branch(bare):
    return git(bare, "rev-parse", "--verify", "-q", "refs/heads/feature", check=False).returncode == 0


def test_failing_on_done_blocks_the_push(installed, remote):
    set_checks(installed, {"onDone": [{"name": "unit", "cmd": "echo boom-output; exit 3"}]})
    code, out = push(installed)
    assert code != 0
    assert "echo boom-output; exit 3" in out and "boom-output" in out
    assert not remote_has_branch(remote)


def test_green_on_done_lets_the_push_through(installed, remote):
    set_checks(installed, {"onDone": [{"name": "unit", "cmd": "true"}, {"name": "lint", "cmd": "exit 0"}]})
    code, out = push(installed)
    assert code == 0, out
    assert remote_has_branch(remote)


def test_on_done_runs_in_the_repo_root(installed, remote):
    set_checks(installed, {"onDone": [{"name": "where", "cmd": "test -f src/calc.py"}]})
    code, out = push(installed)
    assert code == 0, out


def test_push_without_checks_json_hints_and_passes(installed, remote):
    code, out = push(installed)
    assert code == 0, out
    assert "checks.json" in out
    assert remote_has_branch(remote)


# ---------------------------------------------------------------------------
# fail open
# ---------------------------------------------------------------------------

def test_missing_engine_fails_open_with_a_warning(repo, tmp_path):
    copy = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "bin", copy / "bin")
    shutil.copytree(PLUGIN / "hooks", copy / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    code, out = okeanos(repo, "githooks", cli=copy / "bin" / "okeanos")
    assert code == 0, out
    shutil.rmtree(copy)
    (repo / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, out = commit(repo)
    assert code == 0, out
    assert "okeanos" in out.lower()


def test_broken_engine_fails_open_with_a_warning(repo, tmp_path):
    copy = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "bin", copy / "bin")
    shutil.copytree(PLUGIN / "hooks", copy / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    okeanos(repo, "githooks", cli=copy / "bin" / "okeanos")
    shutil.rmtree(copy / "hooks" / "okeanos_engine")
    (repo / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, out = commit(repo)
    assert code == 0, out
    assert "okeanos" in out.lower()


def test_missing_python_fails_open_with_a_warning(installed, tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    (fake_bin / "git").symlink_to(shutil.which("git"))
    (installed / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n')
    code, out = commit(installed, env=clean_env(path=str(fake_bin)))
    assert code == 0, out
    assert "python3" in out
