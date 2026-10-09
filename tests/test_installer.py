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
COPILOT_HOOKS = {"sessionStart", "preToolUse", "postToolUse", "agentStop"}

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


def install(home, fakebin, *args, extra_path="", env_extra=None, cli="install"):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OKEANOS_", "CODEX_", "CLAUDE", "COPILOT_")) and k != "PATH"}
    env.update(env_extra or {})
    env["OKEANOS_HOME_DIR"] = str(home)
    env["FAKE_STATE"] = str(fakebin.parent / "state")
    env["PATH"] = os.pathsep.join(p for p in (str(fakebin), extra_path, "/usr/bin", "/bin") if p)
    p = subprocess.run([sys.executable, str(CLI), cli, *args], capture_output=True, text=True,
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


def test_reinstall_replaces_links_left_by_renamed_skills(home, fakebin):
    # A 1.x install linked the skills under their old names; the clone still holds those folders' parent.
    add_agent(fakebin, "codex")
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    for old in ("tdd", "to-spec", "grilling"):
        (skills / old).symlink_to(ROOT / "skills" / "engineering" / old)
    code, out = install(home, fakebin)
    assert code == 0, out
    assert not any(os.path.lexists(skills / old) for old in ("tdd", "to-spec", "grilling"))
    assert (skills / "okeanos-tdd").is_symlink() and (skills / "okeanos-spec").is_symlink()
    assert (skills / "okeanos-grill" / "SKILL.md").exists()
    install(home, fakebin, "--uninstall")


def test_skill_name_taken_by_the_user_is_left_alone(home, fakebin):
    add_agent(fakebin, "codex")
    taken = home / ".agents" / "skills" / "okeanos-tdd"
    taken.mkdir(parents=True)
    (taken / "SKILL.md").write_text("---\nname: okeanos-tdd\ndescription: the user's own\n---\n")
    code, out = install(home, fakebin)
    assert code == 0, out
    assert not taken.is_symlink() and "the user's own" in (taken / "SKILL.md").read_text()
    assert "okeanos-tdd" in out
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


def cursor_install(home, fakebin, *args, cwd=None, cli="install"):
    """`okeanos install` run from cwd (a temp dir by default, never this repository)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OKEANOS_", "CODEX_", "COPILOT_", "CLAUDE", "CURSOR")) and k != "PATH"}
    env["OKEANOS_HOME_DIR"] = str(home)
    env["FAKE_STATE"] = str(fakebin.parent / "state")
    env["PATH"] = os.pathsep.join((str(fakebin), "/usr/bin", "/bin"))
    p = subprocess.run([sys.executable, str(CLI), cli, *args], capture_output=True, text=True, env=env,
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


# copilot
# ---------------------------------------------------------------------------

def copilot_hooks(home):
    return json.loads((home / ".copilot" / "hooks" / "okeanos.json").read_text())


def copilot_commands(data):
    return [h["bash"] for entries in data["hooks"].values() for h in entries
            if "okeanos" in h.get("bash", "") or str(ROOT) in h.get("bash", "")]


def test_copilot_is_detected_on_the_path(home, fakebin):
    add_agent(fakebin, "copilot")
    code, out = install(home, fakebin)
    assert code == 0, out
    assert "copilot:" in out and "codex: não encontrado" in out
    assert (home / ".copilot" / "hooks" / "okeanos.json").exists()
    assert not (home / ".codex").exists()


def test_copilot_install_puts_every_piece_in_place(home, fakebin):
    add_agent(fakebin, "copilot")
    code, out = install(home, fakebin, "--agent", "copilot")
    assert code == 0, out
    for name in SKILLS:
        link = home / ".agents" / "skills" / name
        assert link.is_symlink() and (link / "SKILL.md").is_file(), name
    assert (home / ".copilot" / "copilot-instructions.md").read_text() == BLOCK
    data = copilot_hooks(home)
    assert data["version"] == 1
    assert set(data["hooks"]) == COPILOT_HOOKS
    commands = copilot_commands(data)
    for sub in ("session-start", "pre-tool", "post-tool", "stop"):
        assert any(c.endswith(f"--agent copilot {sub}") and str(ROOT / "hooks" / "run") in c for c in commands), sub
    assert any("onboard-check.sh" in c and "--agent copilot" in c for c in commands)
    stop = data["hooks"]["agentStop"][0]
    assert stop["type"] == "command" and stop["timeoutSec"] >= 600
    assert (home / ".local" / "bin" / "okeanos").is_symlink()
    assert "reinicie" in out.lower()


def test_copilot_second_run_is_idempotent(home, fakebin):
    add_agent(fakebin, "copilot")
    add_agent(fakebin, "codex")
    install(home, fakebin)
    first = snapshot(home)
    code, out = install(home, fakebin)
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


@pytest.mark.parametrize("args", [["--project"], ["--agent", "copilot", "--project"],
                                  ["--agent", "codex,cursor", "--project"]])
def test_project_is_only_for_cursor_or_codex(home, fakebin, project, args):
    code, out = cursor_install(home, fakebin, *args, cwd=project)
    assert code != 0 and "cursor" in out and "codex" in out
    assert not (project / ".cursor").exists() and not (project / ".codex").exists()


def test_doctor_shows_cursor_status(home, fakebin, project):
    add_agent(fakebin, "cursor")
    doctor = lambda: cursor_install(home, fakebin, cli="doctor", cwd=project)[1].splitlines()  # noqa: E731
    assert any(l.strip().startswith("cursor:") and "não instalado" in l for l in doctor())
    cursor_install(home, fakebin)
    cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=project)
    lines = doctor()
    line = next(l for l in lines if l.strip().startswith("cursor:") and "instalado" in l)
    assert "não instalado" not in line and "hooks" in line and "skills" in line
    assert any("okeanos.mdc" in l and l.rstrip().endswith("sim") for l in lines)


def test_cursor_project_outside_a_repository_is_refused(home, fakebin, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    code, out = cursor_install(home, fakebin, "--agent", "cursor", "--project", cwd=outside)
    assert code != 0 and "git" in out
    assert list(outside.iterdir()) == []


def test_copilot_user_content_is_preserved_and_backed_up(home, fakebin):
    add_agent(fakebin, "copilot")
    cdir = home / ".copilot"
    (cdir / "hooks").mkdir(parents=True)
    user_md = "# Minhas instruções\n\nResponda curto.\n"
    (cdir / "copilot-instructions.md").write_text(user_md)
    mine = {"version": 1, "hooks": {"agentStop": [{"type": "command", "bash": "notify-send done"}]}}
    (cdir / "hooks" / "mine.json").write_text(json.dumps(mine))
    (cdir / "settings.json").write_text('{"model": "gpt-5.5"}')

    code, out = install(home, fakebin)
    assert code == 0, out
    md = (cdir / "copilot-instructions.md").read_text()
    assert md.startswith(user_md) and BLOCK in md
    assert (cdir / "copilot-instructions.md.okeanos-bak").read_text() == user_md
    assert json.loads((cdir / "hooks" / "mine.json").read_text()) == mine
    assert (cdir / "settings.json").read_text() == '{"model": "gpt-5.5"}'

    code, out = install(home, fakebin, "--uninstall")
    assert code == 0, out
    assert (cdir / "copilot-instructions.md").read_text() == user_md
    assert not (cdir / "hooks" / "okeanos.json").exists()
    assert json.loads((cdir / "hooks" / "mine.json").read_text()) == mine
    assert not any((home / ".agents" / "skills" / n).exists() for n in SKILLS)


def test_copilot_hand_edits_to_the_okeanos_hooks_file_survive(home, fakebin):
    add_agent(fakebin, "copilot")
    install(home, fakebin)
    path = home / ".copilot" / "hooks" / "okeanos.json"
    data = json.loads(path.read_text())
    data["hooks"]["agentStop"].append({"type": "command", "bash": "my-notifier"})
    path.write_text(json.dumps(data))
    install(home, fakebin)
    assert {"type": "command", "bash": "my-notifier"} in copilot_hooks(home)["hooks"]["agentStop"]
    install(home, fakebin, "--uninstall")
    left = json.loads(path.read_text())
    assert left["hooks"] == {"agentStop": [{"type": "command", "bash": "my-notifier"}]}


def test_skills_shared_with_codex_stay_until_the_last_agent_leaves(home, fakebin):
    add_agent(fakebin, "copilot")
    add_agent(fakebin, "codex")
    install(home, fakebin)
    code, out = install(home, fakebin, "--uninstall", "--agent", "copilot")
    assert code == 0, out
    assert not (home / ".copilot" / "hooks" / "okeanos.json").exists()
    assert all((home / ".agents" / "skills" / n).is_symlink() for n in SKILLS)
    code, out = install(home, fakebin, "--uninstall", "--agent", "codex")
    assert code == 0, out
    assert not any((home / ".agents" / "skills" / n).exists() for n in SKILLS)


@pytest.mark.parametrize("content", ["{ not json", '{"version": 1, "hooks": []}'])
def test_invalid_copilot_hooks_file_aborts_without_writing(home, fakebin, content):
    add_agent(fakebin, "copilot")
    hooks = home / ".copilot" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "okeanos.json").write_text(content)
    before = snapshot(home)
    code, out = install(home, fakebin, "--agent", "copilot")
    assert code != 0
    assert str(hooks / "okeanos.json") in out
    assert {k: v for k, v in snapshot(home).items() if not k.startswith(".local")} == before


def test_copilot_disabled_hooks_are_reported(home, fakebin):
    add_agent(fakebin, "copilot")
    (home / ".copilot").mkdir()
    (home / ".copilot" / "settings.json").write_text('{"disableAllHooks": true}')
    code, out = install(home, fakebin)
    assert code == 0 and "disableAllHooks" in out


def test_copilot_home_is_ignored_when_the_home_is_redirected(home, fakebin, tmp_path):
    add_agent(fakebin, "copilot")
    elsewhere = tmp_path / "real-copilot-home"
    code, out = install(home, fakebin, env_extra={"COPILOT_HOME": str(elsewhere)})
    assert code == 0, out
    assert not elsewhere.exists()
    assert (home / ".copilot" / "hooks" / "okeanos.json").exists()


def test_copilot_dry_run_writes_nothing(home, fakebin):
    add_agent(fakebin, "copilot")
    code, out = install(home, fakebin, "--dry-run", "--agent", "copilot")
    assert code == 0, out
    assert snapshot(home) == {}
    assert "copilot-instructions.md" in out and "okeanos.json" in out


def test_doctor_shows_copilot_status(home, fakebin):
    add_agent(fakebin, "copilot")
    code, out = install(home, fakebin, cli="doctor")
    assert any(l.strip().startswith("copilot") and "não instalado" in l for l in out.splitlines()), out
    install(home, fakebin)
    code, out = install(home, fakebin, cli="doctor")
    line = next(l for l in out.splitlines() if l.strip().startswith("copilot:") and "instalado" in l)
    assert "não instalado" not in line and "hooks" in line


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


# ---------------------------------------------------------------------------
# codex --codex-hooks toml: the hooks go to [hooks] tables in config.toml
# ---------------------------------------------------------------------------

import tomllib  # noqa: E402

ORCA_HOOKS = {"hooks": {ev: [{"hooks": [{"type": "command", "command": f"/home/u/.orca/agent-hooks/codex-hook.sh {ev}"}]}]
                        for ev in ("PreToolUse", "SessionStart", "Stop")}}
USER_TOML = ('model = "gpt-5.5"  # mine\n\n[projects."/home/u/x"]\ntrust_level = "trusted"\n\n[hooks.state]\n\n'
             '[hooks.state."/home/u/.codex/hooks.json:pre_tool_use:0:0"]\ntrusted_hash = "sha256:abc"\n')


def orca_codex(home, toml=USER_TOML, hooks=ORCA_HOOKS):
    codex = home / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text(json.dumps(hooks, indent=2))
    (codex / "config.toml").write_text(toml)
    return codex


def toml_okeanos_commands(config):
    return [h["command"] for groups in config.get("hooks", {}).values() if isinstance(groups, list)
            for g in groups for h in g.get("hooks", []) if str(ROOT) in h.get("command", "")]


def test_codex_hooks_toml_puts_the_hooks_in_config_toml(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_codex(home)
    hooks_before = (codex / "hooks.json").read_text()
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code == 0, out
    assert (codex / "hooks.json").read_text() == hooks_before  # Orca's file is left alone
    text = (codex / "config.toml").read_text()
    assert text.startswith(USER_TOML)
    assert "# okeanos:start\n" in text and text.endswith("# okeanos:end\n")
    config = tomllib.loads(text)
    assert config["model"] == "gpt-5.5"
    assert config["hooks"]["state"] == {"/home/u/.codex/hooks.json:pre_tool_use:0:0": {"trusted_hash": "sha256:abc"}}
    assert set(k for k in config["hooks"] if k != "state") == CODEX_HOOKS
    commands = toml_okeanos_commands(config)
    for sub in ("session-start", "prompt", "pre-tool", "post-tool", "stop"):
        assert any(c.endswith(f"--agent codex {sub}") for c in commands), sub
    assert config["hooks"]["PreToolUse"][0]["matcher"] == "Bash|apply_patch"
    assert config["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 1800
    assert (codex / "config.toml.okeanos-bak").read_text() == USER_TOML
    assert "/hooks" in out and "config.toml" in out

    first = snapshot(home)
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code == 0, out
    assert snapshot(home) == first

    code, out = install(home, fakebin, "--agent", "codex", "--uninstall")
    assert code == 0, out
    assert (codex / "config.toml").read_text() == USER_TOML
    assert (codex / "hooks.json").read_text() == hooks_before


def test_switching_to_toml_drops_stale_okeanos_entries_from_hooks_json(home, fakebin):
    add_agent(fakebin, "codex")
    codex = home / ".codex"
    install(home, fakebin, "--agent", "codex")  # plain hooks.json install
    data = json.loads((codex / "hooks.json").read_text())
    data["hooks"]["PreToolUse"].insert(0, ORCA_HOOKS["hooks"]["PreToolUse"][0])
    (codex / "hooks.json").write_text(json.dumps(data))
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code == 0, out
    left = json.loads((codex / "hooks.json").read_text())
    assert okeanos_commands(left) == []
    assert left["hooks"]["PreToolUse"] == ORCA_HOOKS["hooks"]["PreToolUse"]
    assert toml_okeanos_commands(tomllib.loads((codex / "config.toml").read_text()))


def test_codex_trust_state_written_inside_the_block_survives_reinstall(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_codex(home)
    install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    text = (codex / "config.toml").read_text()
    trusted = '[hooks.state."/home/u/.codex/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "sha256:def"\n'
    (codex / "config.toml").write_text(text.replace("# okeanos:end\n", trusted + "# okeanos:end\n"))
    code, out = install(home, fakebin, "--agent", "codex", "--uninstall")
    assert code == 0, out
    config = tomllib.loads((codex / "config.toml").read_text())
    assert config["hooks"]["state"]["/home/u/.codex/config.toml:pre_tool_use:0:0"] == {"trusted_hash": "sha256:def"}
    assert "okeanos:start" not in (codex / "config.toml").read_text()


@pytest.mark.parametrize("toml", [
    '[hooks]\nPreToolUse = [{ matcher = "Bash", hooks = [{ type = "command", command = "x" }] }]\n',
    'hooks.Stop = []\n',
])
def test_conflicting_hooks_table_in_config_toml_aborts_untouched(home, fakebin, toml):
    add_agent(fakebin, "codex")
    orca_codex(home, toml=toml)
    before = snapshot(home)
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code != 0
    assert "config.toml" in out and "[hooks]" in out
    assert {k: v for k, v in snapshot(home).items() if not k.startswith(".local")} == before


def test_codex_hooks_flag_forces_json_even_under_orca(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_codex(home)
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "json")
    assert code == 0, out
    assert okeanos_commands(json.loads((codex / "hooks.json").read_text()))
    assert (codex / "config.toml").read_text() == USER_TOML


def test_codex_hooks_flag_forces_toml_without_orca(home, fakebin):
    add_agent(fakebin, "codex")
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code == 0, out
    codex = home / ".codex"
    assert not (codex / "hooks.json").exists()
    assert toml_okeanos_commands(tomllib.loads((codex / "config.toml").read_text()))
    assert "/hooks" in out


def test_codex_toml_dry_run_writes_nothing(home, fakebin):
    add_agent(fakebin, "codex")
    orca_codex(home)
    before = snapshot(home)
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml", "--dry-run")
    assert code == 0, out
    assert snapshot(home) == before
    assert "config.toml" in out


def test_doctor_sees_codex_hooks_in_config_toml(home, fakebin):
    add_agent(fakebin, "codex")
    orca_codex(home)
    install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    code, out = install(home, fakebin, cli="doctor")
    line = next(l for l in out.splitlines() if l.strip().startswith("codex:") and "instalado" in l)
    assert "não instalado" not in line and "hooks" in line and "config.toml" in line


# ---------------------------------------------------------------------------
# codex --project: hooks in <repo>/.codex/hooks.json (Orca regenerates CODEX_HOME, so user hooks don't survive)
# ---------------------------------------------------------------------------

ORCA_NOTE = ("Codex gerenciado pelo Orca: hooks do Okeanos precisam ser instalados por projeto: "
             "okeanos install --agent codex --project (em cada projeto)")
PROJECT_USER_HOOKS = {"other": True, "hooks": {"PreToolUse": [
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "./scripts/guard.sh"}]}]}}


def project_hooks(project):
    return json.loads((project / ".codex" / "hooks.json").read_text())


def orca_home(home, toml=USER_TOML):
    codex = orca_codex(home, toml=toml)
    (codex / ".orca-managed-home").write_text("")
    return codex


def test_codex_project_merges_hooks_into_the_repository(home, fakebin, project):
    (project / ".codex").mkdir()
    original = json.dumps(PROJECT_USER_HOOKS, indent=2) + "\n"
    (project / ".codex" / "hooks.json").write_text(original)
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project / "sub")
    assert code == 0, out
    data = project_hooks(project)
    assert data["other"] is True and set(data["hooks"]) == CODEX_HOOKS
    assert data["hooks"]["PreToolUse"][0] == PROJECT_USER_HOOKS["hooks"]["PreToolUse"][0]
    commands = okeanos_commands(data)
    for sub in ("session-start", "prompt", "pre-tool", "post-tool", "stop"):
        assert any(c.endswith(f"--agent codex {sub}") and str(ROOT / "hooks" / "run") in c for c in commands), sub
    assert (project / ".codex" / "hooks.json.okeanos-bak").read_text() == original
    assert snapshot(home) == {}  # nothing at user level, not even the CLI link
    assert "/hooks" in out and ".codex/hooks.json" in out and "commit" in out.lower()

    first = snapshot(project)
    assert cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project)[0] == 0
    assert snapshot(project) == first

    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", "--uninstall", cwd=project)
    assert code == 0, out
    assert project_hooks(project) == PROJECT_USER_HOOKS


def test_codex_project_uninstall_removes_a_file_that_only_had_okeanos(home, fakebin, project):
    assert cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project)[0] == 0
    assert okeanos_commands(project_hooks(project))
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", "--uninstall", cwd=project)
    assert code == 0, out
    assert not (project / ".codex" / "hooks.json").exists()


def test_codex_project_dry_run_writes_nothing(home, fakebin, project):
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", "--dry-run", cwd=project)
    assert code == 0, out
    assert ".codex/hooks.json" in out and not (project / ".codex").exists()


def test_codex_project_outside_a_repository_is_refused(home, fakebin, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=outside)
    assert code != 0 and "git" in out
    assert list(outside.iterdir()) == []


def test_codex_project_invalid_hooks_file_aborts_untouched(home, fakebin, project):
    (project / ".codex").mkdir()
    (project / ".codex" / "hooks.json").write_text("{not json")
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project)
    assert code != 0 and "hooks.json" in out
    assert (project / ".codex" / "hooks.json").read_text() == "{not json"
    assert not (project / ".codex" / "hooks.json.okeanos-bak").exists()


def test_codex_project_warns_when_user_level_hooks_would_run_twice(home, fakebin, project):
    add_agent(fakebin, "codex")
    cursor_install(home, fakebin, "--agent", "codex")
    code, out = cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project)
    assert code == 0, out
    assert "duas vezes" in out


def test_orca_managed_codex_home_gets_no_user_level_hooks(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_home(home)
    hooks_before = (codex / "hooks.json").read_text()
    code, out = install(home, fakebin, "--agent", "codex")
    assert code == 0, out
    assert (codex / "hooks.json").read_text() == hooks_before
    assert (codex / "config.toml").read_text() == USER_TOML
    assert (codex / "AGENTS.md").read_text() == BLOCK
    for name in SKILLS:
        assert (home / ".agents" / "skills" / name).is_symlink(), name
    assert ORCA_NOTE in out


def test_orca_managed_codex_home_ignores_the_codex_hooks_flag(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_home(home)
    hooks_before = (codex / "hooks.json").read_text()
    code, out = install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    assert code == 0, out
    assert (codex / "hooks.json").read_text() == hooks_before
    assert (codex / "config.toml").read_text() == USER_TOML
    assert ORCA_NOTE in out


def test_orca_managed_codex_home_migrates_the_old_config_toml_block(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_codex(home)
    install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")  # the previous mode
    assert "# okeanos:start" in (codex / "config.toml").read_text()
    (codex / ".orca-managed-home").write_text("")
    code, out = install(home, fakebin, "--agent", "codex")
    assert code == 0, out
    assert (codex / "config.toml").read_text() == USER_TOML
    assert okeanos_commands(json.loads((codex / "hooks.json").read_text())) == []


def test_plain_codex_install_migrates_the_old_config_toml_block_to_hooks_json(home, fakebin):
    add_agent(fakebin, "codex")
    codex = orca_codex(home, hooks={"hooks": {}})
    install(home, fakebin, "--agent", "codex", "--codex-hooks", "toml")
    code, out = install(home, fakebin, "--agent", "codex")
    assert code == 0, out
    assert (codex / "config.toml").read_text() == USER_TOML
    assert okeanos_commands(json.loads((codex / "hooks.json").read_text()))


def test_doctor_shows_orca_and_codex_project_hooks(home, fakebin, project):
    add_agent(fakebin, "codex")
    doctor = lambda: cursor_install(home, fakebin, cli="doctor", cwd=project)[1].splitlines()  # noqa: E731
    lines = doctor()
    assert any("Orca" in l and l.rstrip().endswith("não") for l in lines), lines
    assert any(".codex/hooks.json" in l and l.rstrip().endswith("não") for l in lines), lines
    orca_home(home)
    cursor_install(home, fakebin, "--agent", "codex")
    cursor_install(home, fakebin, "--agent", "codex", "--project", cwd=project)
    lines = doctor()
    assert any("Orca" in l and l.rstrip().endswith("sim") for l in lines), lines
    assert any(".codex/hooks.json" in l and l.rstrip().endswith("sim") for l in lines), lines
    line = next(l for l in lines if l.strip().startswith("codex:") and "instalado" in l)
    assert "instruções" in line and "skills" in line
