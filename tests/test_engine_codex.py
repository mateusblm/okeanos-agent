"""The Okeanos engine seen by OpenAI Codex.

Drives hooks/okeanos.py --agent codex only through its CLI, with payloads in the
shape Codex documents (https://learn.chatgpt.com/docs/hooks): shell commands come
as tool_name "Bash" with tool_input.command, file edits as tool_name "apply_patch"
with the patch text in tool_input.command. Codex can't "ask" in PreToolUse, so
every approval becomes a deny whose last line is the `okeanos aprovar` command.
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
    """One Codex hook call. Returns (exit_code, parsed_stdout_or_None)."""
    full_env = {k: v for k, v in os.environ.items() if k != "OKEANOS_HOOK_DEBUG"}
    full_env.update(env or {})
    stdin = raw if raw is not None else json.dumps(payload)
    p = subprocess.run([sys.executable, str(ENGINE), "--agent", "codex", sub], input=stdin,
                       capture_output=True, text=True, env=full_env, timeout=120, cwd=NEUTRAL_CWD)
    out = p.stdout.strip()
    return p.returncode, (json.loads(out) if out else None)


def common(root, event, session="s1"):
    return {"session_id": session, "transcript_path": None, "cwd": str(root), "hook_event_name": event,
            "model": "gpt-5.5", "turn_id": "t1", "permission_mode": "default"}


def shell(root, command, **kw):
    payload = common(root, "PreToolUse") | {"tool_name": "Bash", "tool_use_id": "c1",
                                             "tool_input": {"command": command}}
    return hook("pre-tool", payload, **kw)


def patch(root, text, event="pre-tool", **kw):
    name = "PreToolUse" if event == "pre-tool" else "PostToolUse"
    payload = common(root, name) | {"tool_name": "apply_patch", "tool_use_id": "c2", "tool_input": {"command": text}}
    if event == "post-tool":
        payload["tool_response"] = "Success."
    return hook(event, payload, **kw)


def stop(root, last=""):
    return hook("stop", common(root, "Stop") | {"stop_hook_active": False, "last_assistant_message": last})


def session_start(root):
    return hook("session-start", common(root, "SessionStart") | {"source": "startup"})


def denied(out):
    """The Codex PreToolUse deny shape; returns the reason."""
    assert out is not None, "expected a PreToolUse deny, got no output"
    assert set(out) == {"hookSpecificOutput"}
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


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


CHANGE_ASSERTION = """*** Begin Patch
*** Update File: tests/test_calc.py
@@ def test_add():
-    assert add(1, 2) == 3
+    assert add(1, 2) == 4
*** End Patch"""


# ---------------------------------------------------------------------------
# shell: publish gate and hard denies
# ---------------------------------------------------------------------------

def test_push_is_denied_with_the_approval_command(repo):
    code, out = shell(repo, "git push origin feature")
    assert code == 0
    reason = denied(out)
    assert "G2" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_approved_push_is_allowed(repo):
    approve(repo, "push")
    assert shell(repo, "git push", env=CLOCK) == (0, None)


def test_force_push_is_denied_even_if_approved(repo):
    approve(repo, "push")
    reason = denied(shell(repo, "git push --force", env=CLOCK)[1])
    assert "force push" in reason and "okeanos aprovar" not in reason


def test_secret_in_commit_is_denied_without_leaking_it(repo):
    key = "AKIA" + "Q" * 16
    (repo / "src" / "config.py").write_text(f'KEY = "{key}"\n')
    reason = denied(shell(repo, 'git add -A && git commit -m "config"')[1])
    assert "src/config.py: AWS access key" in reason and key not in reason


def test_plain_command_is_allowed(repo):
    assert shell(repo, "ls -la && git status") == (0, None)


def test_shell_command_as_argv_list_is_understood(repo):
    payload = common(repo, "PreToolUse") | {"tool_name": "Bash",
                                             "tool_input": {"command": ["bash", "-lc", "git push"]}}
    assert "okeanos aprovar push" in denied(hook("pre-tool", payload)[1])


def test_agent_running_okeanos_aprovar_is_denied(repo):
    reason = denied(shell(repo, "okeanos aprovar push")[1])
    assert "humano" in reason


# ---------------------------------------------------------------------------
# committed tests are the contract: via shell and via apply_patch
# ---------------------------------------------------------------------------

def test_shell_rewrite_of_committed_test_is_denied(repo):
    reason = denied(shell(repo, "sed -i 's/== 3/== 4/' tests/test_calc.py")[1])
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_patch_changing_committed_assertion_is_denied(repo):
    reason = denied(patch(repo, CHANGE_ASSERTION, env=CLOCK)[1])
    assert "tests/test_calc.py" in reason and "assert add(1, 2) == 3" in reason
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"
    assert "pre-edit:ask" in [e["kind"] for e in metrics(repo)]


def test_approved_patch_is_allowed(repo):
    approve(repo, "tests/test_calc.py")
    assert patch(repo, CHANGE_ASSERTION, env=CLOCK) == (0, None)
    assert "pre-edit:approved" in [e["kind"] for e in metrics(repo)]


def test_patch_adding_a_test_is_allowed(repo):
    text = """*** Begin Patch
*** Update File: tests/test_calc.py
@@ def test_add_negative():
     assert add(-1, -2) == -3
+
+
+def test_add_zero():
+    assert add(0, 0) == 0
*** End Patch"""
    assert patch(repo, text) == (0, None)


def test_patch_deleting_committed_test_is_denied(repo):
    text = "*** Begin Patch\n*** Delete File: tests/test_calc.py\n*** End Patch"
    assert "okeanos aprovar tests/test_calc.py" in denied(patch(repo, text)[1])


def test_patch_moving_committed_test_away_is_denied(repo):
    text = ("*** Begin Patch\n*** Update File: tests/test_calc.py\n*** Move to: tests/old_calc.txt\n"
            "@@\n from src.calc import add\n*** End Patch")
    assert "okeanos aprovar tests/test_calc.py" in denied(patch(repo, text)[1])


def test_patch_with_absolute_path_is_understood(repo):
    text = CHANGE_ASSERTION.replace("tests/test_calc.py", str(repo / "tests" / "test_calc.py"))
    assert "okeanos aprovar tests/test_calc.py" in denied(patch(repo, text)[1])


def test_patch_relative_to_a_subdirectory_is_understood(repo):
    payload = common(repo / "tests", "PreToolUse") | {
        "tool_name": "apply_patch", "tool_input": {"command": CHANGE_ASSERTION.replace("tests/test_calc.py", "test_calc.py")}}
    assert "okeanos aprovar tests/test_calc.py" in denied(hook("pre-tool", payload)[1])


def test_unparseable_patch_on_committed_test_is_denied_as_a_rewrite(repo):
    text = "*** Begin Patch\n*** Update File: tests/test_calc.py\n??? garbled hunk\n*** End Patch"
    assert "okeanos aprovar tests/test_calc.py" in denied(patch(repo, text)[1])


def test_unparseable_patch_on_source_file_is_allowed(repo):
    text = "*** Begin Patch\n*** Update File: src/calc.py\n??? garbled hunk\n*** End Patch"
    assert patch(repo, text) == (0, None)


def test_patch_touching_two_tests_names_both_in_one_command(repo):
    (repo / "tests" / "test_more.py").write_text("def test_more():\n    assert True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more")
    text = CHANGE_ASSERTION.replace("*** End Patch", "*** Delete File: tests/test_more.py\n*** End Patch")
    reason = denied(patch(repo, text)[1])
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py tests/test_more.py"
    assert sum(l.startswith("Para aprovar") for l in reason.splitlines()) == 1


def test_apply_patch_heredoc_in_the_shell_is_checked(repo):
    command = "apply_patch <<'EOF'\n" + CHANGE_ASSERTION + "\nEOF"
    assert "okeanos aprovar tests/test_calc.py" in denied(shell(repo, command)[1])


def test_patch_writing_okeanos_state_is_denied(repo):
    text = "*** Begin Patch\n*** Add File: .git/okeanos/approvals.json\n+{}\n*** End Patch"
    assert "humano" in denied(patch(repo, text)[1])


# ---------------------------------------------------------------------------
# post-tool: per-file checks go back to the agent
# ---------------------------------------------------------------------------

def test_post_patch_failing_check_blocks(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "echo LINT-ERR; exit 1", "ext": [".py"]}]})
    text = "*** Begin Patch\n*** Update File: src/calc.py\n@@\n-    return a + b\n+    return b + a\n*** End Patch"
    code, out = patch(repo, text, event="post-tool")
    assert code == 0
    assert out["decision"] == "block" and "LINT-ERR" in out["reason"] and "src/calc.py" in out["reason"]


# ---------------------------------------------------------------------------
# stop: definition of done
# ---------------------------------------------------------------------------

def test_session_start_records_the_start_head(repo):
    assert session_start(repo) == (0, None)
    state = json.loads((repo / ".git" / "okeanos" / "sessions" / "s1.json").read_text())
    assert state["start_head"] == git(repo, "rev-parse", "HEAD")


def test_failing_done_continues_the_turn(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo)
    assert code == 0
    assert out["decision"] == "block"
    assert "FAILED" in out["reason"] and "tentativa 1/3" in out["reason"] and HANDOFF in out["reason"]
    assert {e["agent"] for e in metrics(repo)} == {"codex"}


def test_handoff_line_lets_codex_stop_with_a_warning(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo, last="Preciso de uma decisão.\n\n" + HANDOFF)
    assert code == 0 and set(out) == {"systemMessage"}


def test_passing_done_is_silent(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "true"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo) == (0, None)


def test_first_prompt_gets_the_route_reminder(repo):
    payload = common(repo, "UserPromptSubmit") | {"prompt": "add a sub function"}
    code, out = hook("prompt", payload)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "rota" in out["hookSpecificOutput"]["additionalContext"]
    assert hook("prompt", payload) == (0, None)


# ---------------------------------------------------------------------------
# fail-open
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub", ["pre-tool", "post-tool", "stop", "prompt", "session-start"])
def test_garbage_stdin_allows(sub):
    assert hook(sub, None, raw="not json{") == (0, None)


@pytest.mark.parametrize("sub", ["pre-tool", "post-tool", "stop", "prompt", "session-start"])
@pytest.mark.parametrize("payload", [{}, {"cwd": 7}, {"tool_name": "apply_patch", "tool_input": "x"},
                                     {"tool_name": "Bash", "tool_input": {"command": 7}}, []])
def test_payload_without_usable_fields_allows(sub, payload):
    assert hook(sub, payload) == (0, None)


def test_other_tools_are_allowed(repo):
    payload = common(repo, "PreToolUse") | {"tool_name": "mcp__fs__write", "tool_input": {"path": "tests/test_calc.py"}}
    assert hook("pre-tool", payload) == (0, None)


# ---------------------------------------------------------------------------
# onboard check: AGENTS.md is Codex's context file
# ---------------------------------------------------------------------------

def onboard(root, agent):
    p = subprocess.run([str(ONBOARD), "--agent", agent], input=json.dumps({"cwd": str(root)}),
                       capture_output=True, text=True, timeout=30)
    return p.stdout.strip()


def test_onboard_check_asks_codex_for_agents_md(repo):
    out = json.loads(onboard(repo, "codex"))
    note = out["hookSpecificOutput"]["additionalContext"]
    assert "AGENTS.md" in note and "`onboard` skill" in note and "Skill tool" not in note


def test_onboard_check_accepts_agents_md_in_codex(repo):
    (repo / "AGENTS.md").write_text("# proj\n")
    set_checks(repo, {"onDone": []})
    assert onboard(repo, "codex") == ""


def test_onboard_check_in_claude_still_wants_claude_md(repo):
    (repo / "AGENTS.md").write_text("# proj\n")
    set_checks(repo, {"onDone": []})
    assert "CLAUDE.md" in onboard(repo, "claude")
