"""`okeanos install`: the one installer, driven as a subprocess against a fake HOME.

OKEANOS_HOME_DIR redirects every user path; PATH holds only fake agent CLIs
(plus the system tools), so nothing touches the real HOME or the network.
The fake `claude` records its arguments and keeps a tiny plugin state.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "okeanos"
BLOCK = (ROOT / "adapters" / "agents-md" / "okeanos.md").read_text()
SKILLS = [p.split("/")[-1] for p in json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["skills"]]
CODEX_HOOKS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}

FAKE_CLAUDE = """#!/bin/sh
echo "$*" >> "$FAKE_STATE/log"
echo "$HOME" >> "$FAKE_STATE/home"
case "$*" in
  "plugin marketplace list --json") cat "$FAKE_STATE/mkts" 2>/dev/null || echo '[]' ;;
  "plugin list --json") cat "$FAKE_STATE/plugins" 2>/dev/null || echo '[]' ;;
  "plugin marketplace add "*) echo '[{"name": "okeanos"}]' > "$FAKE_STATE/mkts" ;;
  "plugin install okeanos@okeanos") echo '[{"id": "okeanos@okeanos"}]' > "$FAKE_STATE/plugins" ;;
  "plugin uninstall okeanos@okeanos") echo '[]' > "$FAKE_STATE/plugins" ;;
  "plugin marketplace remove okeanos") echo '[]' > "$FAKE_STATE/mkts" ;;
esac
"""


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def fakebin(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir()
    (tmp_path / "state").mkdir()
    return d


def add_agent(fakebin, name):
    path = fakebin / name
    path.write_text(FAKE_CLAUDE if name == "claude" else "#!/bin/sh\nexit 0\n")
    path.chmod(0o755)


def install(home, fakebin, *args, extra_path=""):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OKEANOS_", "CODEX_", "CLAUDE")) and k != "PATH"}
    env["OKEANOS_HOME_DIR"] = str(home)
    env["FAKE_STATE"] = str(fakebin.parent / "state")
    env["PATH"] = os.pathsep.join(p for p in (str(fakebin), extra_path, "/usr/bin", "/bin") if p)
    p = subprocess.run([sys.executable, str(CLI), "install", *args], capture_output=True, text=True,
                       env=env, stdin=subprocess.DEVNULL, timeout=120)
    return p.returncode, p.stdout + p.stderr


def snapshot(home):
    """Every path under home: file content, or the symlink target."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(home):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(home))
            if path.is_symlink():
                out[rel] = "-> " + os.readlink(path)
            elif path.is_file():
                out[rel] = path.read_text()
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
    return out


def claude_log(fakebin):
    log = fakebin.parent / "state" / "log"
    return log.read_text().splitlines() if log.exists() else []


def okeanos_commands(hooks_json):
    return [h["command"] for groups in hooks_json["hooks"].values() for g in groups for h in g["hooks"]
            if "okeanos" in h.get("command", "") or str(ROOT) in h.get("command", "")]


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

def test_no_agent_found_changes_nothing(home, fakebin):
    code, out = install(home, fakebin)
    assert code == 0
    assert "nenhum agente" in out.lower()
    assert snapshot(home) == {}


def test_only_found_agents_are_installed(home, fakebin):
    add_agent(fakebin, "codex")
    code, out = install(home, fakebin)
    assert code == 0, out
    assert "codex" in out and "claude: não encontrado" in out
    assert claude_log(fakebin) == []


# ---------------------------------------------------------------------------
# codex
# ---------------------------------------------------------------------------

def test_codex_install_puts_every_piece_in_place(home, fakebin):
    add_agent(fakebin, "codex")
    code, out = install(home, fakebin)
    assert code == 0, out
    for name in SKILLS:
        link = home / ".agents" / "skills" / name
        assert link.is_symlink() and (link / "SKILL.md").is_file(), name
        assert Path(os.path.realpath(link)).is_relative_to(ROOT / "skills")
    assert (home / ".codex" / "AGENTS.md").read_text() == BLOCK
    hooks = json.loads((home / ".codex" / "hooks.json").read_text())
    assert set(hooks["hooks"]) == CODEX_HOOKS
    commands = okeanos_commands(hooks)
    for sub in ("session-start", "prompt", "pre-tool", "post-tool", "stop"):
        assert any(c.endswith(f"--agent codex {sub}") and str(ROOT / "hooks" / "run") in c for c in commands), sub
    assert any("onboard-check.sh" in c and "--agent codex" in c for c in commands)
    cli = home / ".local" / "bin" / "okeanos"
    assert cli.is_symlink() and os.path.realpath(cli) == str(CLI)
    assert "/hooks" in out  # Codex runs new hooks only after the user trusts them
    assert "não está no PATH" in out


def test_second_run_is_idempotent(home, fakebin):
    add_agent(fakebin, "codex")
    add_agent(fakebin, "claude")
    install(home, fakebin)
    first = snapshot(home)
    code, out = install(home, fakebin)
    assert code == 0, out
    assert snapshot(home) == first
    assert sum(l.startswith("plugin install") for l in claude_log(fakebin)) == 1


def test_user_content_is_preserved_and_backed_up(home, fakebin):
    add_agent(fakebin, "codex")
    codex = home / ".codex"
    codex.mkdir()
    user_md = "# Minhas instruções\n\nUse pnpm.\n"
    (codex / "AGENTS.md").write_text(user_md)
    user_hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-guard"}]}]},
                  "other": 1}
    (codex / "hooks.json").write_text(json.dumps(user_hooks))
    (codex / "config.toml").write_text('model = "gpt-5.5"\n')
    mine = home / ".agents" / "skills" / "mine"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("---\nname: mine\ndescription: x\n---\n")

    code, out = install(home, fakebin)
    assert code == 0, out
    md = (codex / "AGENTS.md").read_text()
    assert md.startswith(user_md) and BLOCK in md
    hooks = json.loads((codex / "hooks.json").read_text())
    assert hooks["other"] == 1
    assert {"type": "command", "command": "my-guard"} in hooks["hooks"]["PreToolUse"][0]["hooks"]
    assert okeanos_commands(hooks)
    assert (codex / "AGENTS.md.okeanos-bak").read_text() == user_md
    assert json.loads((codex / "hooks.json.okeanos-bak").read_text()) == user_hooks
    assert (codex / "config.toml").read_text() == 'model = "gpt-5.5"\n'

    code, out = install(home, fakebin, "--uninstall")
    assert code == 0, out
    assert (codex / "AGENTS.md").read_text() == user_md
    assert json.loads((codex / "hooks.json").read_text()) == user_hooks
    assert (mine / "SKILL.md").exists()
    assert not any((home / ".agents" / "skills" / n).exists() for n in SKILLS)
    assert not (home / ".local" / "bin" / "okeanos").exists()


def test_skill_name_taken_by_the_user_is_left_alone(home, fakebin):
    add_agent(fakebin, "codex")
    taken = home / ".agents" / "skills" / "tdd"
    taken.mkdir(parents=True)
    (taken / "SKILL.md").write_text("---\nname: tdd\ndescription: the user's own\n---\n")
    code, out = install(home, fakebin)
    assert code == 0, out
    assert not taken.is_symlink() and "the user's own" in (taken / "SKILL.md").read_text()
    assert "tdd" in out
    install(home, fakebin, "--uninstall")
    assert (taken / "SKILL.md").exists()


@pytest.mark.parametrize("name,content", [
    ("hooks.json", "{ not json"),
    ("hooks.json", '{"hooks": []}'),
    ("config.toml", "model = = broken"),
])
def test_invalid_codex_config_aborts_without_writing(home, fakebin, name, content):
    add_agent(fakebin, "codex")
    codex = home / ".codex"
    codex.mkdir()
    (codex / name).write_text(content)
    before = snapshot(home)
    code, out = install(home, fakebin, "--agent", "codex")
    assert code != 0
    assert str(codex / name) in out
    assert {k: v for k, v in snapshot(home).items() if not k.startswith(".local")} == before


def test_agents_override_is_reported(home, fakebin):
    add_agent(fakebin, "codex")
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.override.md").write_text("override\n")
    code, out = install(home, fakebin)
    assert code == 0 and "AGENTS.override.md" in out


def test_dry_run_writes_nothing(home, fakebin):
    add_agent(fakebin, "codex")
    add_agent(fakebin, "claude")
    code, out = install(home, fakebin, "--dry-run")
    assert code == 0, out
    assert snapshot(home) == {}
    assert not any(l.startswith(("plugin install", "plugin marketplace add")) for l in claude_log(fakebin))
    assert "AGENTS.md" in out and "plugin install okeanos@okeanos" in out


def test_local_bin_on_path_gives_no_warning(home, fakebin):
    add_agent(fakebin, "codex")
    code, out = install(home, fakebin, extra_path=str(home / ".local" / "bin"))
    assert code == 0 and "não está no PATH" not in out


# ---------------------------------------------------------------------------
# cursor: user hooks in ~/.cursor/hooks.json, shared skills, rules per project
# ---------------------------------------------------------------------------

CURSOR_HOOKS = {"sessionStart": "session-start", "beforeShellExecution": "shell", "preToolUse": "pre-tool",
                "postToolUse": "post-tool", "afterAgentResponse": "agent-response", "stop": "stop"}


def cursor_install(home, fakebin, *args, cwd=None):
    """`okeanos install` run from cwd (a temp dir by default, never this repository)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OKEANOS_", "CODEX_", "CLAUDE", "CURSOR")) and k != "PATH"}
    env["OKEANOS_HOME_DIR"] = str(home)
    env["FAKE_STATE"] = str(fakebin.parent / "state")
    env["PATH"] = os.pathsep.join((str(fakebin), "/usr/bin", "/bin"))
    p = subprocess.run([sys.executable, str(CLI), "install", *args], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=120, cwd=cwd or str(home.parent))
    return p.returncode, p.stdout + p.stderr


def cursor_entries(home):
    data = json.loads((home / ".cursor" / "hooks.json").read_text())
    return data, {event: [h for h in entries if "--agent cursor" in h.get("command", "")]
                  for event, entries in data["hooks"].items()}


@pytest.mark.parametrize("found_by", ["cursor", "cursor-agent", "config-dir"])
def test_cursor_is_detected(home, fakebin, found_by):
    if found_by == "config-dir":
        (home / ".cursor").mkdir()
    else:
        add_agent(fakebin, found_by)
    code, out = cursor_install(home, fakebin)
    assert code == 0, out
    assert (home / ".cursor" / "hooks.json").exists()


def test_cursor_install_puts_every_piece_in_place(home, fakebin):
    add_agent(fakebin, "cursor")
    code, out = cursor_install(home, fakebin)
    assert code == 0, out
    data, ours = cursor_entries(home)
    assert data["version"] == 1
    assert set(data["hooks"]) == set(CURSOR_HOOKS)
    for event, sub in CURSOR_HOOKS.items():
        commands = [h["command"] for h in ours[event]]
        assert any(c.endswith(f"--agent cursor {sub}") and str(ROOT / "hooks" / "run") in c for c in commands), event
    assert any("onboard-check.sh" in h["command"] for h in ours["sessionStart"])
    assert all(h.get("matcher") for h in ours["preToolUse"] + ours["postToolUse"])
    assert "Shell" not in ours["preToolUse"][0]["matcher"]  # beforeShellExecution covers the shell
    for name in SKILLS:
        link = home / ".agents" / "skills" / name
        assert link.is_symlink() and (link / "SKILL.md").is_file(), name
    # no file-based global rules in Cursor: say how to enable per project
    assert "--project" in out and "Rules" in out
    assert not (home / ".cursor" / "rules").exists()
    assert (home / ".local" / "bin" / "okeanos").is_symlink()


def test_cursor_second_run_is_idempotent(home, fakebin):
    add_agent(fakebin, "cursor")
    cursor_install(home, fakebin)
    first = snapshot(home)
    code, out = cursor_install(home, fakebin)
    assert code == 0, out
    assert snapshot(home) == first


def test_cursor_user_hooks_are_preserved_backed_up_and_restored(home, fakebin):
    add_agent(fakebin, "cursor")
    (home / ".cursor").mkdir()
    user = {"version": 1, "hooks": {"stop": [{"command": "./audit.sh", "loop_limit": 10}],
                                    "afterFileEdit": [{"command": "./format.sh"}]}}
    (home / ".cursor" / "hooks.json").write_text(json.dumps(user))
    code, out = cursor_install(home, fakebin)
    assert code == 0, out
    data, ours = cursor_entries(home)
    assert {"command": "./audit.sh", "loop_limit": 10} in data["hooks"]["stop"]
    assert data["hooks"]["afterFileEdit"] == [{"command": "./format.sh"}]
    assert ours["stop"]
    assert json.loads((home / ".cursor" / "hooks.json.okeanos-bak").read_text()) == user
    code, out = cursor_install(home, fakebin, "--uninstall", "--agent", "cursor")
    assert code == 0, out
    assert json.loads((home / ".cursor" / "hooks.json").read_text()) == user
    assert not any((home / ".agents" / "skills" / n).exists() for n in SKILLS)


@pytest.mark.parametrize("content", ["{ not json", '{"version": 1, "hooks": []}',
                                     '{"version": 1, "hooks": {"stop": {"command": "x"}}}'])
def test_invalid_cursor_hooks_abort_without_writing(home, fakebin, content):
    add_agent(fakebin, "cursor")
    (home / ".cursor").mkdir()
    (home / ".cursor" / "hooks.json").write_text(content)
    before = snapshot(home)
    code, out = cursor_install(home, fakebin, "--agent", "cursor")
    assert code != 0
    assert str(home / ".cursor" / "hooks.json") in out
    assert {k: v for k, v in snapshot(home).items() if not k.startswith(".local")} == before


def test_cursor_dry_run_writes_nothing(home, fakebin):
    add_agent(fakebin, "cursor")
    code, out = cursor_install(home, fakebin, "--dry-run", "--agent", "cursor")
    assert code == 0, out
    assert snapshot(home) == {}
    assert "hooks.json" in out


def test_uninstalling_cursor_keeps_the_skills_codex_still_uses(home, fakebin):
    add_agent(fakebin, "cursor")
    add_agent(fakebin, "codex")
    cursor_install(home, fakebin)
    code, out = cursor_install(home, fakebin, "--uninstall", "--agent", "cursor")
    assert code == 0, out
    assert not cursor_entries(home)[1].get("stop")
    assert all((home / ".agents" / "skills" / n).is_symlink() for n in SKILLS)
    assert "codex" in out
    code, out = cursor_install(home, fakebin, "--uninstall")
    assert code == 0, out
    assert not any((home / ".agents" / "skills" / n).exists() for n in SKILLS)


# --project: the process as a Cursor project rule in the current repository

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_cursor_project_writes_an_always_applied_rule(home, fakebin, project):
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=project / "sub")
    assert code == 0, out
    rule = (project / ".cursor" / "rules" / "okeanos.mdc").read_text()
    assert rule.startswith("---\n") and "alwaysApply: true" in rule.split("---")[1]
    assert BLOCK in rule
    assert not (home / ".cursor").exists() and not (home / ".local").exists()
    first = snapshot(project)
    assert cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=project)[0] == 0
    assert snapshot(project) == first
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", "--uninstall", cwd=project)
    assert code == 0, out
    assert not (project / ".cursor" / "rules" / "okeanos.mdc").exists()


def test_cursor_project_leaves_a_users_rule_alone(home, fakebin, project):
    rules = project / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "okeanos.mdc").write_text("---\nalwaysApply: true\n---\nmine\n")
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=project)
    assert code != 0 and "okeanos.mdc" in out
    assert (rules / "okeanos.mdc").read_text() == "---\nalwaysApply: true\n---\nmine\n"


def test_cursor_project_dry_run_writes_nothing(home, fakebin, project):
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", "--dry-run", cwd=project)
    assert code == 0, out
    assert "okeanos.mdc" in out and not (project / ".cursor").exists()


@pytest.mark.parametrize("args", [["--project"], ["--agent", "codex", "--project"]])
def test_project_is_only_for_cursor(home, fakebin, project, args):
    code, out = cursor_install(home, fakebin, *args, cwd=project)
    assert code != 0 and "cursor" in out
    assert not (project / ".cursor").exists()


def test_cursor_project_outside_a_repository_is_refused(home, fakebin, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=outside)
    assert code != 0 and "git" in out
    assert list(outside.iterdir()) == []


# ---------------------------------------------------------------------------
# claude code: delegate to the marketplace, never touch its settings
# ---------------------------------------------------------------------------

def test_claude_install_uses_the_marketplace(home, fakebin):
    add_agent(fakebin, "claude")
    code, out = install(home, fakebin)
    assert code == 0, out
    log = claude_log(fakebin)
    assert f"plugin marketplace add {ROOT}" in log
    assert "plugin install okeanos@okeanos" in log
    assert not (home / ".claude").exists()


def test_claude_runs_with_the_redirected_home(home, fakebin):
    add_agent(fakebin, "claude")
    install(home, fakebin)
    install(home, fakebin, "--uninstall")
    seen = set((fakebin.parent / "state" / "home").read_text().splitlines())
    assert seen == {str(home)}


def test_claude_already_installed_is_left_alone(home, fakebin):
    add_agent(fakebin, "claude")
    state = fakebin.parent / "state"
    (state / "mkts").write_text('[{"name": "okeanos"}]')
    (state / "plugins").write_text('[{"id": "okeanos@okeanos"}]')
    code, out = install(home, fakebin)
    assert code == 0, out
    assert not any(l.startswith(("plugin install", "plugin marketplace add")) for l in claude_log(fakebin))
    assert "já instalado" in out


def test_uninstall_one_agent_keeps_the_others(home, fakebin):
    add_agent(fakebin, "claude")
    add_agent(fakebin, "codex")
    install(home, fakebin)
    code, out = install(home, fakebin, "--uninstall", "--agent", "claude")
    assert code == 0, out
    assert "plugin uninstall okeanos@okeanos" in claude_log(fakebin)
    assert (home / ".codex" / "AGENTS.md").exists()
    assert (home / ".local" / "bin" / "okeanos").is_symlink()


def test_unknown_agent_is_refused(home, fakebin):
    code, out = install(home, fakebin, "--agent", "gemini")
    assert code != 0 and "gemini" in out
    assert snapshot(home) == {}


# ---------------------------------------------------------------------------
# install.sh: clone or update, then hand over to `okeanos install`
# ---------------------------------------------------------------------------

def test_install_sh_clones_then_updates_and_passes_arguments(tmp_path):
    src = tmp_path / "src"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "okeanos").write_text('#!/usr/bin/env python3\nimport sys\nprint("ARGS", *sys.argv[1:])\n')
    (src / "bin" / "okeanos").chmod(0o755)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "i"]):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True)
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("OKEANOS_")}
    env.update({"OKEANOS_REPO": str(src), "OKEANOS_HOME_DIR": str(home)})
    for _ in range(2):
        p = subprocess.run(["sh", str(ROOT / "install.sh"), "--dry-run"], capture_output=True, text=True,
                           env=env, timeout=60)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "ARGS install --dry-run" in p.stdout
    assert (home / ".local" / "share" / "okeanos" / "bin" / "okeanos").exists()
