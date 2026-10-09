"""The Okeanos engine seen by GitHub Copilot (CLI and cloud agent).

Drives hooks/okeanos.py --agent copilot only through its CLI, with payloads in the
two shapes Copilot documents (https://docs.github.com/en/copilot/reference/hooks-reference):

- camelCase (`version: 1` config with camelCase event names): sessionId, cwd, toolName
  ("bash", "edit", "create", ...) and toolArgs, which the CLI sends as a JSON *string*;
- VS Code compatible (PascalCase event names): session_id, cwd, hook_event_name, tool_name
  with the Claude tool name ("Bash", "Edit", "Write") and tool_input.

The CLI honours permissionDecision "ask"; the cloud agent (recognised by COPILOT_AGENT_PROMPT
in the hook's environment) treats ask as deny, so there the engine denies and keeps the
`okeanos aprovar` line.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "hooks" / "okeanos.py"
ONBOARD = ROOT / "hooks" / "onboard-check.sh"
HANDOFF = "[Okeanos] precisa de você"
OLD_HANDOFF = "**Okeanos** · precisa de você"  # sessions mid-flight still use it
NEUTRAL_CWD = tempfile.mkdtemp(prefix="okeanos-neutral-")
NOW = 1_800_000_000
CLOCK = {"OKEANOS_NOW": str(NOW)}
CLOUD = {"COPILOT_AGENT_PROMPT": "Fix the failing test"}

TEST_FILE = """from src.calc import add


def test_add():
    assert add(1, 2) == 3


def test_add_negative():
    assert add(-1, -2) == -3
"""

SRC_FILE = """def add(a, b):
    return a + b
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text(SRC_FILE)
    (root / "tests" / "test_calc.py").write_text(TEST_FILE)
    git(root, "init", "-q", "-b", "feature")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def set_checks(root, checks):
    d = root / "docs" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "checks.json").write_text(json.dumps(checks))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "checks")


def hook(sub, payload, *, raw=None, env=None):
    """One Copilot hook call. Returns (exit_code, parsed_stdout_or_None)."""
    full_env = {k: v for k, v in os.environ.items()
                if k != "OKEANOS_HOOK_DEBUG" and not k.startswith("COPILOT_")}
    full_env.update(env or {})
    stdin = raw if raw is not None else json.dumps(payload)
    p = subprocess.run([sys.executable, str(ENGINE), "--agent", "copilot", sub], input=stdin,
                       capture_output=True, text=True, env=full_env, timeout=120, cwd=NEUTRAL_CWD)
    out = p.stdout.strip()
    return p.returncode, (json.loads(out) if out else None)


# --- camelCase payloads (the CLI's native format) ---------------------------

def camel(root, session="s1"):
    return {"sessionId": session, "timestamp": 1704614400000, "cwd": str(root)}


def tool(root, name, args, event="pre-tool", as_string=True, **kw):
    payload = camel(root) | {"toolName": name, "toolArgs": json.dumps(args) if as_string else args}
    if event == "post-tool":
        payload["toolResult"] = {"resultType": "success", "textResultForLlm": "ok"}
    return hook(event, payload, **kw)


def shell(root, command, **kw):
    return tool(root, "bash", {"command": command, "description": "run"}, **kw)


def stop(root, **kw):
    return hook("stop", camel(root) | {"transcriptPath": "/tmp/t.jsonl", "stopReason": "end_turn",
                                       "stop_hook_active": False}, **kw)


def session_start(root, session="s1"):
    return hook("session-start", camel(root, session) | {"source": "new", "initialPrompt": "oi"})


# --- VS Code compatible payloads (PascalCase event names) -------------------

def pascal(root, event, session="s1"):
    return {"hook_event_name": event, "session_id": session, "timestamp": "2026-10-08T12:00:00.000Z",
            "cwd": str(root)}


def pascal_tool(root, name, tool_input, **kw):
    return hook("pre-tool", pascal(root, "PreToolUse") | {"tool_name": name, "tool_input": tool_input}, **kw)


# --- output shapes ----------------------------------------------------------

def decided(out, decision):
    """The camelCase preToolUse decision; returns the reason."""
    assert out is not None, f"expected {decision}, got no output"
    assert out["permissionDecision"] == decision, out
    return out["permissionDecisionReason"]


def pascal_decided(out, decision):
    """VS Code compatible output: the top-level fields plus Claude-style hookSpecificOutput."""
    reason = decided(out, decision)
    hso = out["hookSpecificOutput"]
    assert hso == {"hookEventName": "PreToolUse", "permissionDecision": decision,
                   "permissionDecisionReason": reason}
    return reason


def metrics(root):
    path = root / ".git" / "okeanos" / "metrics.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def approve(root, *targets):
    path = root / ".git" / "okeanos" / "approvals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    for t in targets:
        data[t] = {"approved_at": NOW, "expires_at": NOW + 600}
    path.write_text(json.dumps(data))


def change_assertion(root):
    return {"path": str(root / "tests" / "test_calc.py"),
            "old_str": "    assert add(1, 2) == 3", "new_str": "    assert add(1, 2) == 4"}


# ---------------------------------------------------------------------------
# shell: publish gate and hard denies
# ---------------------------------------------------------------------------

def test_push_asks_in_the_cli(repo):
    code, out = shell(repo, "git push origin feature")
    assert code == 0
    reason = decided(out, "ask")
    assert "G2" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_push_is_denied_in_the_cloud_agent_with_the_approval_command(repo):
    reason = decided(shell(repo, "git push origin feature", env=CLOUD)[1], "deny")
    assert "G2" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_tool_args_as_an_object_are_understood_too(repo):
    code, out = tool(repo, "bash", {"command": "git push"}, as_string=False)
    assert decided(out, "ask").splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_approved_push_is_allowed(repo):
    approve(repo, "push")
    assert shell(repo, "git push", env=CLOCK) == (0, None)


def test_secret_in_commit_is_denied_without_leaking_it(repo):
    key = "AKIA" + "Q" * 16
    (repo / "src" / "config.py").write_text(f'KEY = "{key}"\n')
    reason = decided(shell(repo, 'git add -A && git commit -m "config"')[1], "deny")
    assert "src/config.py: AWS access key" in reason and key not in reason


def test_plain_command_is_allowed(repo):
    assert shell(repo, "ls -la && git status") == (0, None)


def test_agent_running_okeanos_aprovar_is_denied(repo):
    assert "humano" in decided(shell(repo, "okeanos aprovar push")[1], "deny")


# ---------------------------------------------------------------------------
# committed tests: via shell and via the edit/create tools
# ---------------------------------------------------------------------------

def test_shell_rewrite_of_committed_test_asks(repo):
    reason = decided(shell(repo, "sed -i 's/== 3/== 4/' tests/test_calc.py")[1], "ask")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_edit_changing_committed_assertion_asks(repo):
    reason = decided(tool(repo, "edit", change_assertion(repo), env=CLOCK)[1], "ask")
    assert "assert add(1, 2) == 3" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"
    assert "pre-edit:ask" in [e["kind"] for e in metrics(repo)]
    assert {e["agent"] for e in metrics(repo)} == {"copilot"}


def test_edit_changing_committed_assertion_is_denied_in_the_cloud(repo):
    reason = decided(tool(repo, "edit", change_assertion(repo), env=CLOUD)[1], "deny")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_edit_with_a_relative_path_is_understood(repo):
    args = change_assertion(repo) | {"path": "test_calc.py"}
    payload = camel(repo / "tests") | {"toolName": "edit", "toolArgs": json.dumps(args)}
    assert "okeanos aprovar tests/test_calc.py" in decided(hook("pre-tool", payload)[1], "ask")


def test_approved_edit_is_allowed(repo):
    approve(repo, "tests/test_calc.py")
    assert tool(repo, "edit", change_assertion(repo), env=CLOCK) == (0, None)


def test_edit_adding_a_test_is_allowed(repo):
    args = {"path": str(repo / "tests" / "test_calc.py"), "old_str": "    assert add(-1, -2) == -3\n",
            "new_str": "    assert add(-1, -2) == -3\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n"}
    assert tool(repo, "edit", args) == (0, None)


def test_create_over_committed_test_asks(repo):
    args = {"path": str(repo / "tests" / "test_calc.py"), "file_text": "def test_nothing():\n    pass\n"}
    assert "okeanos aprovar tests/test_calc.py" in decided(tool(repo, "create", args)[1], "ask")


def test_str_replace_editor_is_understood(repo):
    args = change_assertion(repo) | {"command": "str_replace"}
    assert "okeanos aprovar tests/test_calc.py" in decided(tool(repo, "str_replace_editor", args)[1], "ask")


def test_apply_patch_on_committed_test_asks(repo):
    patch = ("*** Begin Patch\n*** Update File: tests/test_calc.py\n@@ def test_add():\n"
             "-    assert add(1, 2) == 3\n+    assert add(1, 2) == 4\n*** End Patch")
    assert "okeanos aprovar tests/test_calc.py" in decided(tool(repo, "apply_patch", {"input": patch})[1], "ask")


def test_edit_writing_okeanos_state_is_denied(repo):
    args = {"path": str(repo / ".git" / "okeanos" / "approvals.json"), "file_text": "{}"}
    assert "humano" in decided(tool(repo, "create", args)[1], "deny")


# ---------------------------------------------------------------------------
# the VS Code compatible (PascalCase) variant
# ---------------------------------------------------------------------------

def test_pascal_push_asks(repo):
    reason = pascal_decided(pascal_tool(repo, "Bash", {"command": "git push"})[1], "ask")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_pascal_push_is_denied_in_the_cloud(repo):
    reason = pascal_decided(pascal_tool(repo, "Bash", {"command": "git push"}, env=CLOUD)[1], "deny")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_pascal_edit_of_committed_assertion_asks(repo):
    reason = pascal_decided(pascal_tool(repo, "Edit", change_assertion(repo))[1], "ask")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_pascal_edit_with_claude_field_names_asks(repo):
    ti = {"file_path": str(repo / "tests" / "test_calc.py"), "old_string": "    assert add(1, 2) == 3",
          "new_string": "    assert add(1, 2) == 4"}
    assert "okeanos aprovar tests/test_calc.py" in pascal_decided(pascal_tool(repo, "Edit", ti)[1], "ask")


def test_pascal_write_over_committed_test_asks(repo):
    ti = {"path": str(repo / "tests" / "test_calc.py"), "file_text": "def test_nothing():\n    pass\n"}
    assert "okeanos aprovar tests/test_calc.py" in pascal_decided(pascal_tool(repo, "Write", ti)[1], "ask")


def test_pascal_approved_edit_is_allowed(repo):
    approve(repo, "tests/test_calc.py")
    assert pascal_tool(repo, "Edit", change_assertion(repo), env=CLOCK) == (0, None)


def test_pascal_secret_is_denied(repo):
    (repo / "src" / "config.py").write_text('KEY = "AKIA' + "Q" * 16 + '"\n')
    reason = pascal_decided(pascal_tool(repo, "Bash", {"command": "git commit -am x"})[1], "deny")
    assert "AWS access key" in reason


def test_pascal_failing_done_blocks_the_stop(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    hook("session-start", pascal(repo, "SessionStart") | {"source": "new"})
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    payload = pascal(repo, "Stop") | {"transcript_path": "/tmp/t", "stop_reason": "end_turn",
                                      "stop_hook_active": False}
    out = hook("stop", payload)[1]
    assert out["decision"] == "block" and "FAILED" in out["reason"]


# ---------------------------------------------------------------------------
# post-tool: per-file checks go back to the agent as additional context
# ---------------------------------------------------------------------------

def test_post_edit_failing_check_goes_back_as_context(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "echo LINT-ERR; exit 1", "ext": [".py"]}]})
    args = {"path": str(repo / "src" / "calc.py"), "old_str": "a + b", "new_str": "b + a"}
    code, out = tool(repo, "edit", args, event="post-tool")
    assert code == 0
    assert "LINT-ERR" in out["additionalContext"] and "src/calc.py" in out["additionalContext"]


# ---------------------------------------------------------------------------
# session start and stop: definition of done
# ---------------------------------------------------------------------------

def test_session_start_records_the_start_head_and_reminds_the_route_once(repo):
    code, out = session_start(repo)
    assert code == 0 and "rota" in out["additionalContext"]
    state = json.loads((repo / ".git" / "okeanos" / "sessions" / "s1.json").read_text())
    assert state["start_head"] == git(repo, "rev-parse", "HEAD")
    assert session_start(repo) == (0, None)


def test_failing_done_continues_the_turn(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo)
    assert code == 0
    assert out["decision"] == "block"
    assert "FAILED" in out["reason"] and "tentativa 1/3" in out["reason"] and HANDOFF in out["reason"]


def test_handoff_line_in_the_transcript_lets_copilot_stop(repo, tmp_path):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    transcript = tmp_path / "events.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user.message", "data": {"content": "faça"}},
        {"type": "assistant.message", "data": {"content": "Preciso de uma decisão.\n\n" + HANDOFF}},
        {"type": "tool.execution_complete", "data": {}},
    ]) + "\n")
    payload = camel(repo) | {"transcriptPath": str(transcript), "stopReason": "end_turn", "stop_hook_active": False}
    assert hook("stop", payload) == (0, None)


def test_old_handoff_line_in_the_transcript_still_lets_copilot_stop(repo, tmp_path):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    transcript = tmp_path / "events.jsonl"
    transcript.write_text(json.dumps({"type": "assistant.message",
                                      "data": {"content": "Preciso de uma decisão.\n\n" + OLD_HANDOFF}}) + "\n")
    payload = camel(repo) | {"transcriptPath": str(transcript), "stopReason": "end_turn", "stop_hook_active": False}
    assert hook("stop", payload) == (0, None)


def test_failing_done_also_blocks_in_the_cloud(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo, env=CLOUD)[1]["decision"] == "block"


def test_passing_done_is_silent(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "true"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo) == (0, None)


# ---------------------------------------------------------------------------
# fail-open
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub", ["pre-tool", "post-tool", "stop", "prompt", "session-start"])
def test_garbage_stdin_allows(sub):
    assert hook(sub, None, raw="not json{") == (0, None)


@pytest.mark.parametrize("sub", ["pre-tool", "post-tool", "stop", "prompt", "session-start"])
@pytest.mark.parametrize("payload", [{}, {"cwd": 7}, {"toolName": "bash", "toolArgs": "{not json"},
                                     {"toolName": "bash", "toolArgs": 7},
                                     {"tool_name": "Bash", "tool_input": {"command": 7}}, []])
def test_payload_without_usable_fields_allows(sub, payload):
    assert hook(sub, payload) == (0, None)


def test_other_tools_are_allowed(repo):
    assert tool(repo, "view", {"path": str(repo / "tests" / "test_calc.py")}) == (0, None)


# ---------------------------------------------------------------------------
# onboard check: Copilot reads AGENTS.md, CLAUDE.md or .github/copilot-instructions.md
# ---------------------------------------------------------------------------

def onboard(root, agent="copilot"):
    p = subprocess.run([str(ONBOARD), "--agent", agent], input=json.dumps({"cwd": str(root)}),
                       capture_output=True, text=True, timeout=30)
    return p.stdout.strip()


def test_onboard_check_speaks_copilot(repo):
    out = json.loads(onboard(repo))
    assert set(out) == {"additionalContext"}
    assert "AGENTS.md" in out["additionalContext"] and "`onboard` skill" in out["additionalContext"]


@pytest.mark.parametrize("context", ["AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"])
def test_onboard_check_accepts_any_file_copilot_reads(repo, context):
    (repo / context).parent.mkdir(parents=True, exist_ok=True)
    (repo / context).write_text("# proj\n")
    set_checks(repo, {"onDone": []})
    assert onboard(repo) == ""
