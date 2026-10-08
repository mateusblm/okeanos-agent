"""The Okeanos engine seen by the Cursor IDE agent.

Drives hooks/okeanos.py --agent cursor only through its CLI, with payloads in the
shape Cursor documents (https://cursor.com/docs/agent/hooks):
  - beforeShellExecution: `command`, `cwd`; answers `permission` allow|deny|ask (ask is enforced).
  - preToolUse: `tool_name` (Write, Delete, and StrReplace for in-place edits), `tool_input`
    (`file_path` or `path`, `content`, `old_string`/`new_string`); `ask` is NOT enforced
    there, so every approval becomes a deny whose last line is the `okeanos aprovar` command.
  - postToolUse: `additional_context` goes back to the agent.
  - stop: `status`, `loop_count`; `followup_message` continues the conversation.
  - afterAgentResponse: `text`, remembered so stop can see the handoff line.
Every event carries conversation_id and workspace_roots; `cwd` may be empty.
Permission hooks always answer with JSON: Cursor blocks on output it can't parse.
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
HANDOFF = "**Okeanos** · precisa de você"
NEUTRAL_CWD = tempfile.mkdtemp(prefix="okeanos-neutral-")
NOW = 1_800_000_000
CLOCK = {"OKEANOS_NOW": str(NOW)}
ALLOW = {"permission": "allow"}

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
    """One Cursor hook call. Returns (exit_code, parsed_stdout_or_None)."""
    full_env = {k: v for k, v in os.environ.items() if k != "OKEANOS_HOOK_DEBUG"}
    full_env.update(env or {})
    stdin = raw if raw is not None else json.dumps(payload)
    p = subprocess.run([sys.executable, str(ENGINE), "--agent", "cursor", sub], input=stdin,
                       capture_output=True, text=True, env=full_env, timeout=120, cwd=NEUTRAL_CWD)
    out = p.stdout.strip()
    return p.returncode, (json.loads(out) if out else None)


def common(root, event, conversation="c1"):
    return {"conversation_id": conversation, "generation_id": "g1", "model": "gpt-5.5",
            "hook_event_name": event, "cursor_version": "3.13.25", "workspace_roots": [str(root)],
            "user_email": None, "transcript_path": None}


def shell(root, command, **kw):
    payload = common(root, "beforeShellExecution") | {"command": command, "cwd": str(root), "sandbox": False}
    return hook("shell", payload, **kw)


def tool(root, name, tool_input, event="pre-tool", cwd="", **kw):
    hook_event = "preToolUse" if event == "pre-tool" else "postToolUse"
    payload = common(root, hook_event) | {"tool_name": name, "tool_input": tool_input, "tool_use_id": "t1",
                                          "cwd": cwd}
    if event == "post-tool":
        payload |= {"tool_output": "{}", "duration": 12}
    return hook(event, payload, **kw)


def str_replace(root, path, old, new, **kw):
    return tool(root, "StrReplace", {"path": path, "old_string": old, "new_string": new}, **kw)


def stop(root, status="completed", loop_count=0):
    return hook("stop", common(root, "stop") | {"status": status, "loop_count": loop_count})


def agent_response(root, text):
    return hook("agent-response", common(root, "afterAgentResponse") | {"text": text})


def session_start(root):
    return hook("session-start", common(root, "sessionStart") | {"session_id": "c1", "is_background_agent": False,
                                                                 "composer_mode": "agent"})


def refused(out, permission="deny"):
    """The Cursor permission shape; returns the reason the agent reads."""
    assert out is not None, "expected a permission answer, got no output"
    assert out["permission"] == permission, out
    assert out["agent_message"] == out["user_message"]
    return out["agent_message"]


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


# ---------------------------------------------------------------------------
# beforeShellExecution: Cursor enforces ask, so the user approves natively
# ---------------------------------------------------------------------------

def test_push_asks_natively_with_the_approval_command(repo):
    code, out = shell(repo, "git push origin feature")
    assert code == 0
    reason = refused(out, "ask")
    assert "G2" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_approved_push_is_allowed(repo):
    approve(repo, "push")
    assert shell(repo, "git push", env=CLOCK) == (0, ALLOW)


def test_force_push_is_denied_even_if_approved(repo):
    approve(repo, "push")
    reason = refused(shell(repo, "git push --force", env=CLOCK)[1])
    assert "force push" in reason and "okeanos aprovar" not in reason


def test_secret_in_commit_is_denied_without_leaking_it(repo):
    key = "AKIA" + "Q" * 16
    (repo / "src" / "config.py").write_text(f'KEY = "{key}"\n')
    reason = refused(shell(repo, 'git add -A && git commit -m "config"')[1])
    assert "src/config.py: AWS access key" in reason and key not in reason


def test_plain_command_is_allowed(repo):
    assert shell(repo, "ls -la && git status") == (0, ALLOW)


def test_shell_change_to_committed_assertion_needs_approval(repo):
    reason = refused(shell(repo, "sed -i 's/== 3/== 4/' tests/test_calc.py")[1], "ask")
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_agent_running_okeanos_aprovar_is_denied(repo):
    assert "humano" in refused(shell(repo, "okeanos aprovar push")[1])


def test_shell_without_cwd_uses_the_workspace_root(repo):
    payload = common(repo, "beforeShellExecution") | {"command": "git push", "cwd": ""}
    assert "okeanos aprovar push" in refused(hook("shell", payload)[1], "ask")


# ---------------------------------------------------------------------------
# preToolUse: editor tools; ask isn't enforced there, so it becomes deny
# ---------------------------------------------------------------------------

def test_str_replace_changing_committed_assertion_is_denied(repo):
    code, out = str_replace(repo, str(repo / "tests" / "test_calc.py"), "assert add(1, 2) == 3",
                            "assert add(1, 2) == 4", env=CLOCK)
    assert code == 0
    reason = refused(out)
    assert "tests/test_calc.py" in reason and "assert add(1, 2) == 3" in reason
    assert "não pede confirmação" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"
    assert "pre-edit:ask" in [e["kind"] for e in metrics(repo)]
    assert {e["agent"] for e in metrics(repo)} == {"cursor"}


def test_approved_str_replace_is_allowed(repo):
    approve(repo, "tests/test_calc.py")
    out = str_replace(repo, "tests/test_calc.py", "assert add(1, 2) == 3", "assert add(1, 2) == 4", env=CLOCK)
    assert out == (0, ALLOW)
    assert "pre-edit:approved" in [e["kind"] for e in metrics(repo)]


def test_str_replace_adding_a_test_is_allowed(repo):
    old = "    assert add(-1, -2) == -3\n"
    new = old + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"
    assert str_replace(repo, "tests/test_calc.py", old, new) == (0, ALLOW)


def test_write_rewriting_committed_test_is_denied(repo):
    content = TEST_FILE.replace("== 3", "== 4")
    out = tool(repo, "Write", {"file_path": str(repo / "tests" / "test_calc.py"), "content": content})[1]
    assert refused(out).splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_write_without_readable_content_on_committed_test_counts_as_rewrite(repo):
    out = tool(repo, "Write", {"path": str(repo / "tests" / "test_calc.py")})[1]
    assert "okeanos aprovar tests/test_calc.py" in refused(out)


def test_delete_of_committed_test_is_denied(repo):
    out = tool(repo, "Delete", {"path": str(repo / "tests" / "test_calc.py")})[1]
    assert "okeanos aprovar tests/test_calc.py" in refused(out)


def test_write_to_source_file_is_allowed(repo):
    out = tool(repo, "Write", {"file_path": str(repo / "src" / "calc.py"), "content": SRC_FILE + "# x\n"})
    assert out == (0, ALLOW)


def test_write_to_okeanos_state_is_denied(repo):
    out = tool(repo, "Write", {"file_path": str(repo / ".git" / "okeanos" / "approvals.json"), "content": "{}"})[1]
    assert "humano" in refused(out)


def test_shell_through_pre_tool_is_checked_too(repo):
    out = tool(repo, "Shell", {"command": "git push", "cwd": ""})[1]
    reason = refused(out)
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_other_tools_are_allowed(repo):
    assert tool(repo, "Read", {"path": str(repo / "tests" / "test_calc.py")}) == (0, ALLOW)


# ---------------------------------------------------------------------------
# postToolUse: per-file checks go back to the agent as additional context
# ---------------------------------------------------------------------------

def test_post_edit_failing_check_goes_back_to_the_agent(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "echo LINT-ERR; exit 1", "ext": [".py"]}]})
    code, out = tool(repo, "StrReplace", {"path": str(repo / "src" / "calc.py"), "old_string": "a + b",
                                          "new_string": "b + a"}, event="post-tool")
    assert code == 0
    assert set(out) == {"additional_context"}
    assert "LINT-ERR" in out["additional_context"] and "src/calc.py" in out["additional_context"]


def test_post_edit_passing_is_silent(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "true", "ext": [".py"]}]})
    out = tool(repo, "Write", {"file_path": str(repo / "src" / "calc.py"), "content": SRC_FILE}, event="post-tool")
    assert out == (0, None)


# ---------------------------------------------------------------------------
# stop: definition of done as a followup message
# ---------------------------------------------------------------------------

def test_session_start_records_the_start_head(repo):
    assert session_start(repo) == (0, None)
    state = json.loads((repo / ".git" / "okeanos" / "sessions" / "c1.json").read_text())
    assert state["start_head"] == git(repo, "rev-parse", "HEAD")


def test_failing_done_becomes_a_followup_message(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo)
    assert code == 0
    assert set(out) == {"followup_message"}
    assert "FAILED" in out["followup_message"] and "tentativa 1/3" in out["followup_message"]
    assert HANDOFF in out["followup_message"]


def test_aborted_turn_is_not_continued(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo, status="aborted") == (0, None)


def test_handoff_line_in_the_last_response_lets_cursor_stop(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert agent_response(repo, "Preciso de uma decisão.\n\n" + HANDOFF) == (0, None)
    assert stop(repo) == (0, None)
    assert "stop:handoff" in [e["kind"] for e in metrics(repo)]


def test_passing_done_is_silent(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "true"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo) == (0, None)


# ---------------------------------------------------------------------------
# fail-open, with valid JSON on permission hooks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub,expected", [("shell", ALLOW), ("pre-tool", ALLOW), ("post-tool", None),
                                          ("stop", None), ("session-start", None), ("agent-response", None)])
def test_garbage_stdin_allows(sub, expected):
    assert hook(sub, None, raw="not json{") == (0, expected)


@pytest.mark.parametrize("sub,expected", [("shell", ALLOW), ("pre-tool", ALLOW), ("post-tool", None),
                                          ("stop", None), ("session-start", None)])
@pytest.mark.parametrize("payload", [{}, {"cwd": 7}, {"workspace_roots": "x"}, {"tool_name": "Write", "tool_input": "x"},
                                     {"command": 7}, []])
def test_payload_without_usable_fields_allows(sub, expected, payload):
    assert hook(sub, payload) == (0, expected)


# ---------------------------------------------------------------------------
# onboard check: AGENTS.md, answered in Cursor's sessionStart shape
# ---------------------------------------------------------------------------

def onboard(root, agent, payload):
    p = subprocess.run([str(ONBOARD), "--agent", agent], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    return p.stdout.strip()


def test_onboard_check_answers_cursor_with_additional_context(repo):
    out = json.loads(onboard(repo, "cursor", {"workspace_roots": [str(repo)], "session_id": "c1"}))
    assert set(out) == {"additional_context"}
    assert "AGENTS.md" in out["additional_context"] and "`onboard` skill" in out["additional_context"]


def test_onboard_check_accepts_agents_md_in_cursor(repo):
    (repo / "AGENTS.md").write_text("# proj\n")
    set_checks(repo, {"onDone": []})
    assert onboard(repo, "cursor", {"workspace_roots": [str(repo)]}) == ""
