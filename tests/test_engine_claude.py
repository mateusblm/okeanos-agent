"""Parity suite: the Okeanos engine seen by Claude Code.

Drives hooks/okeanos.py only through its CLI (JSON on stdin, Claude Code hook
payloads) against throwaway git repos, and checks stdout, exit code and the
files the engine writes. Never imports engine internals.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "hooks" / "okeanos.py"
RUN = Path(__file__).resolve().parent.parent / "hooks" / "run"
HANDOFF = "**Okeanos** · precisa de você"
# Hooks run from a directory outside any git repo, so a payload without `cwd`
# can never touch the repository running these tests.
NEUTRAL_CWD = tempfile.mkdtemp(prefix="okeanos-neutral-")

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


def set_checks(root, checks, commit=True):
    d = root / "docs" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "checks.json").write_text(json.dumps(checks))
    if commit:
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "checks")


def hook(event, payload, *, raw=None, env=None, argv=None, via_run=False):
    """Run one hook through the CLI. Returns (exit_code, parsed_stdout_or_None)."""
    full_env = {k: v for k, v in os.environ.items() if k != "OKEANOS_HOOK_DEBUG"}
    full_env.update(env or {})
    cmd = [str(RUN)] if via_run else [sys.executable, str(ENGINE)]
    cmd += argv if argv is not None else [event]
    stdin = raw if raw is not None else json.dumps(payload)
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=full_env, timeout=120,
                       cwd=NEUTRAL_CWD)
    out = p.stdout.strip()
    return p.returncode, (json.loads(out) if out else None)


def bash(root, command, session="s1", **kw):
    return hook("pre-bash", {"session_id": session, "cwd": str(root), "hook_event_name": "PreToolUse",
                             "tool_name": "Bash", "tool_input": {"command": command}}, **kw)


def edit(root, tool, tool_input, event="pre-edit", session="s1"):
    name = "PreToolUse" if event == "pre-edit" else "PostToolUse"
    return hook(event, {"session_id": session, "cwd": str(root), "hook_event_name": name,
                        "tool_name": tool, "tool_input": tool_input})


def stop(root, session="s1", last=""):
    return hook("stop", {"session_id": session, "cwd": str(root), "hook_event_name": "Stop",
                         "stop_hook_active": False, "last_assistant_message": last})


def session_start(root, session="s1"):
    return hook("session-start", {"session_id": session, "cwd": str(root), "hook_event_name": "SessionStart",
                                  "source": "startup"})


def decision(out):
    assert out is not None, "expected a PreToolUse decision, got no output"
    hso = out["hookSpecificOutput"]
    assert set(out) == {"hookSpecificOutput"}
    assert set(hso) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
    assert hso["hookEventName"] == "PreToolUse"
    return hso["permissionDecision"], hso["permissionDecisionReason"]


def metrics(root):
    path = root / ".git" / "okeanos" / "metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# pre-bash: publish gate and dangerous commands
# ---------------------------------------------------------------------------

def test_push_asks_for_approval(repo):
    code, out = bash(repo, "git push origin feature")
    assert code == 0
    d, reason = decision(out)
    assert d == "ask"
    assert "G2" in reason and "git push" in reason


def test_pr_create_asks_for_approval(repo):
    d, reason = decision(bash(repo, "gh pr create --fill")[1])
    assert d == "ask" and "gh pr create" in reason


def test_force_push_is_denied(repo):
    d, reason = decision(bash(repo, "git push --force origin feature")[1])
    assert d == "deny" and "force push" in reason


def test_no_verify_is_denied(repo):
    d, reason = decision(bash(repo, "git commit --no-verify -m wip")[1])
    assert d == "deny" and "--no-verify" in reason


def test_recursive_rm_outside_repo_is_denied(repo):
    d, reason = decision(bash(repo, "rm -rf /opt/somewhere/else")[1])
    assert d == "deny" and "fora do repositório" in reason


def test_recursive_rm_inside_repo_is_allowed(repo):
    assert bash(repo, "rm -rf build") == (0, None)


def test_plain_command_is_allowed(repo):
    assert bash(repo, "ls -la && git status") == (0, None)


def test_hook_runs_through_the_run_wrapper(repo):
    d, _ = decision(bash(repo, "git push", via_run=True)[1])
    assert d == "ask"


# ---------------------------------------------------------------------------
# pre-bash: secrets and packages
# ---------------------------------------------------------------------------

def test_secret_in_commit_is_denied_without_leaking_it(repo):
    key = "AKIA" + "Q" * 16
    (repo / "src" / "config.py").write_text(f'KEY = "{key}"\n')
    d, reason = decision(bash(repo, 'git add -A && git commit -m "config"')[1])
    assert d == "deny"
    assert "src/config.py: AWS access key" in reason
    assert key not in reason


def test_clean_commit_is_allowed(repo):
    (repo / "src" / "more.py").write_text("X = 1\n")
    assert bash(repo, 'git commit -am "more"') == (0, None)


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "registry.json"

    def make(table):
        path.write_text(json.dumps(table))
        return {"OKEANOS_REGISTRY_FAKE": str(path)}
    return make


def test_nonexistent_package_is_denied(repo, registry):
    env = registry({"https://registry.npmjs.org/leftpad-hallucinated": 404})
    d, reason = decision(bash(repo, "npm install leftpad-hallucinated", env=env)[1])
    assert d == "deny" and "não existe" in reason and "leftpad-hallucinated" in reason


def test_nonexistent_pypi_package_is_denied(repo, registry):
    env = registry({"https://pypi.org/pypi/reqeusts-pro/json": 404})
    d, _ = decision(bash(repo, "pip install reqeusts-pro==1.0", env=env)[1])
    assert d == "deny"


def test_typo_of_popular_package_asks(repo, registry):
    env = registry({
        "https://registry.npmjs.org/expresss": {"time": {"created": "2015-01-01T00:00:00Z"}},
        "https://api.npmjs.org/downloads/point/last-week/expresss": {"downloads": 50000},
    })
    d, reason = decision(bash(repo, "npm install expresss", env=env)[1])
    assert d == "ask" and "express" in reason


@pytest.fixture
def known_registry(registry):
    """Real packages are known; anything else answers 404, so a stray token would be denied."""
    old = {"time": {"created": "2012-01-01T00:00:00Z"}}
    table = {"https://registry.npmjs.org/lodash": old,
             "https://api.npmjs.org/downloads/point/last-week/lodash": {"downloads": 10 ** 8},
             "https://pypi.org/pypi/requests/json": {"releases": {"1.0": [{"upload_time_iso_8601": "2011-01-01T00:00:00Z"}]}}}
    for tok in ("2>&1", "&>log", "2>", ">", ">>", "<", "/dev/null", "log", "input", "out.txt"):
        table["https://registry.npmjs.org/" + tok] = 404
        table[f"https://pypi.org/pypi/{tok}/json"] = 404
    for name in ("2%3E%261", "%26%3Elog", "2%3E", "%3E", "%3E%3E", "%3C", "%2Fdev%2Fnull"):
        table["https://registry.npmjs.org/" + name] = 404
        table[f"https://pypi.org/pypi/{name}/json"] = 404
    return registry(table)


@pytest.mark.parametrize("command", [
    "npm install lodash 2>&1 | tail -3",
    "pip install requests > /dev/null",
    "pip install requests 2>/dev/null",
    "npm install lodash &>log",
    "npm install lodash < input",
    "npm install lodash >> out.txt 2> /dev/null",
    "pip install requests 2> log",
])
def test_redirections_are_not_package_names(repo, known_registry, command):
    assert bash(repo, command, env=known_registry) == (0, None)


def test_real_package_after_a_redirection_is_still_checked(repo, registry):
    env = registry({"https://registry.npmjs.org/leftpad-hallucinated": 404})
    d, _ = decision(bash(repo, "npm install 2>/dev/null leftpad-hallucinated", env=env)[1])
    assert d == "deny"


def test_unreachable_registry_allows(repo, registry):
    env = registry({})
    assert bash(repo, "npm install some-package", env=env) == (0, None)


# ---------------------------------------------------------------------------
# committed tests are the contract
# ---------------------------------------------------------------------------

def test_edit_changing_committed_assertion_asks(repo):
    d, reason = decision(edit(repo, "Edit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "old_string": "    assert add(1, 2) == 3", "new_string": "    assert add(1, 2) == 4"})[1])
    assert d == "ask" and "tests/test_calc.py" in reason and "assert add(1, 2) == 3" in reason


def test_multiedit_removing_assertion_asks(repo):
    d, _ = decision(edit(repo, "MultiEdit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "edits": [{"old_string": "    assert add(-1, -2) == -3\n", "new_string": "    pass\n"}]})[1])
    assert d == "ask"


def test_write_dropping_assertions_asks(repo):
    d, _ = decision(edit(repo, "Write", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "content": "from src.calc import add\n\n\ndef test_add():\n    pass\n"})[1])
    assert d == "ask"


def test_edit_adding_skip_marker_asks(repo):
    d, _ = decision(edit(repo, "Edit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "old_string": "def test_add_negative():",
        "new_string": "@pytest.mark.skip\ndef test_add_negative():"})[1])
    assert d == "ask"


def test_sed_in_place_with_semicolon_in_quotes_asks(repo):
    d, reason = decision(bash(repo, "sed -i 's/== 3/== 4/; s/== -3/== -4/' tests/test_calc.py")[1])
    assert d == "ask" and "tests/test_calc.py" in reason


def test_redirect_over_committed_test_asks(repo):
    d, reason = decision(bash(repo, "echo 'def test_x(): pass' > tests/test_calc.py")[1])
    assert d == "ask" and "tests/test_calc.py" in reason


def test_additive_test_edit_is_allowed(repo):
    assert edit(repo, "Edit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "old_string": "    assert add(-1, -2) == -3\n",
        "new_string": "    assert add(-1, -2) == -3\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"}) == (0, None)


def test_import_edit_is_allowed(repo):
    assert edit(repo, "Edit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "old_string": "from src.calc import add", "new_string": "from src.calc import add, sub"}) == (0, None)


def test_reformatting_an_assertion_is_allowed(repo):
    assert edit(repo, "Edit", {
        "file_path": str(repo / "tests" / "test_calc.py"),
        "old_string": "    assert add(1, 2) == 3",
        "new_string": "    assert add(\n        1,\n        2,\n    ) == 3"}) == (0, None)


def test_uncommitted_test_file_is_free(repo):
    (repo / "tests" / "test_new.py").write_text("def test_a():\n    assert 1\n")
    assert edit(repo, "Edit", {"file_path": str(repo / "tests" / "test_new.py"),
                               "old_string": "    assert 1", "new_string": "    assert 2"}) == (0, None)


def test_writing_a_new_test_via_shell_is_free(repo):
    assert bash(repo, "echo 'def test_x(): pass' > tests/test_other.py") == (0, None)


# ---------------------------------------------------------------------------
# post-edit
# ---------------------------------------------------------------------------

def test_post_edit_failing_check_blocks(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "echo bad {file}; exit 1", "ext": [".py"]}]})
    code, out = edit(repo, "Edit", {"file_path": str(repo / "src" / "calc.py"),
                                    "old_string": "a + b", "new_string": "b + a"}, event="post-edit")
    assert code == 0
    assert set(out) == {"decision", "reason"}
    assert out["decision"] == "block" and "src/calc.py" in out["reason"] and "[lint]" in out["reason"]


def test_post_edit_passing_check_is_silent(repo):
    set_checks(repo, {"onEdit": [{"name": "lint", "cmd": "true", "ext": [".py"]}]})
    assert edit(repo, "Edit", {"file_path": str(repo / "src" / "calc.py"),
                               "old_string": "a", "new_string": "a"}, event="post-edit") == (0, None)


# ---------------------------------------------------------------------------
# stop: definition of done
# ---------------------------------------------------------------------------

def test_stop_without_changes_is_silent(repo):
    session_start(repo)
    assert stop(repo) == (0, None)


def test_failing_done_blocks_then_escalates_after_three(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "\n\ndef sub(a, b):\n    return a - b\n")
    for attempt in (1, 2, 3):
        code, out = stop(repo)
        assert code == 0
        assert set(out) == {"decision", "reason"}
        assert out["decision"] == "block"
        assert f"tentativa {attempt}/3" in out["reason"] and "FAILED" in out["reason"]
        assert HANDOFF in out["reason"]
    code, out = stop(repo)
    assert set(out) == {"systemMessage"} and "3 vezes" in out["systemMessage"]
    assert stop(repo) == (0, None)  # escalated: same state doesn't block again
    kinds = [e["kind"] for e in metrics(repo)]
    assert kinds.count("stop:block") == 4 and kinds.count("stop:escalate") == 1


def test_handoff_line_lets_the_agent_stop_with_a_message(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo, last="Preciso que você decida.\n\n" + HANDOFF)
    assert code == 0
    assert set(out) == {"systemMessage"} and "decisão sua" in out["systemMessage"]
    assert "stop:handoff" in [e["kind"] for e in metrics(repo)]


def test_passing_done_is_silent(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "true"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo) == (0, None)
    assert "stop:pass" in [e["kind"] for e in metrics(repo)]


def test_formatting_only_test_change_is_not_tamper(repo):
    session_start(repo)
    (repo / "tests" / "test_calc.py").write_text(TEST_FILE.replace(
        "    assert add(1, 2) == 3", "    assert add(\n        1, 2\n    ) == 3"))
    assert stop(repo) == (0, None)


def test_loosened_test_blocks_once_as_tamper(repo):
    session_start(repo)
    (repo / "tests" / "test_calc.py").write_text(TEST_FILE.replace("assert add(1, 2) == 3", "pass"))
    code, out = stop(repo)
    assert out["decision"] == "block" and "asserção" in out["reason"]
    code, out = stop(repo)
    assert set(out) == {"systemMessage"} and "testes alterados" in out["systemMessage"]


def test_new_suppression_blocks_once(repo):
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "import os  # noqa\n")
    code, out = stop(repo)
    assert code == 0
    assert set(out) == {"decision", "reason"}
    assert out["decision"] == "block" and "supressão nova em src/calc.py" in out["reason"]
    code, out = stop(repo)
    assert set(out) == {"systemMessage"} and "supressão" in out["systemMessage"]
    assert stop(repo) == (0, None)


def test_oversized_diff_warns(repo):
    set_checks(repo, {"maxChangedLines": 5})
    session_start(repo)
    (repo / "src" / "big.py").write_text("".join(f"X{i} = {i}\n" for i in range(20)))
    git(repo, "add", "-A")  # tracked, so the numstat counts it
    code, out = stop(repo)
    assert set(out) == {"systemMessage"} and "limite 5" in out["systemMessage"]


# ---------------------------------------------------------------------------
# prompt: route reminder
# ---------------------------------------------------------------------------

def test_first_prompt_gets_route_reminder_once(repo):
    payload = {"session_id": "s1", "cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": "oi"}
    code, out = hook("prompt", payload)
    assert code == 0
    assert set(out) == {"hookSpecificOutput"}
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit" and "rota" in hso["additionalContext"]
    assert hook("prompt", payload) == (0, None)
    assert hook("prompt", {**payload, "session_id": "s2"})[1] is not None


# ---------------------------------------------------------------------------
# fail-open
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("event", ["pre-bash", "pre-edit", "post-edit", "stop", "prompt", "session-start"])
def test_garbage_stdin_allows(event):
    assert hook(event, None, raw="this is not json{") == (0, None)


@pytest.mark.parametrize("event", ["pre-bash", "pre-edit", "post-edit", "stop", "prompt", "session-start"])
@pytest.mark.parametrize("payload", [{}, {"cwd": 7, "session_id": ["x"]}, {"tool_input": None}])
def test_payload_without_usable_fields_allows(event, payload):
    assert hook(event, payload) == (0, None)


@pytest.mark.parametrize("event", ["pre-bash", "pre-edit", "post-edit"])
@pytest.mark.parametrize("tool_input", ["oops", {"command": 7, "file_path": 7}, {"edits": "x", "file_path": "tests/test_calc.py"}])
def test_malformed_tool_input_allows(repo, event, tool_input):
    code, out = hook(event, {"session_id": "s1", "cwd": str(repo), "tool_name": "MultiEdit", "tool_input": tool_input})
    assert (code, out) == (0, None)


def test_unknown_subcommand_allows():
    assert hook(None, {}, argv=["no-such-hook"]) == (0, None)


def test_outside_a_git_repo_allows(tmp_path):
    assert bash(tmp_path, "git push") [0] == 0
    assert hook("stop", {"session_id": "s", "cwd": str(tmp_path)}) == (0, None)


@pytest.mark.parametrize("event", ["pre-bash", "pre-edit", "stop", "prompt"])
@pytest.mark.parametrize("raw", ["[]", "7", "null", '"text"'])
def test_non_object_json_allows_without_error(event, raw):
    assert hook(event, None, raw=raw) == (0, None)


@pytest.mark.parametrize("agent", ["no-such-agent", ""])
def test_unknown_agent_allows(repo, agent):
    payload = {"session_id": "s1", "cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "git push --force"}}
    assert hook(None, payload, argv=["--agent", agent, "pre-bash"]) == (0, None)


# ---------------------------------------------------------------------------
# dialect selection and metrics
# ---------------------------------------------------------------------------

def test_explicit_claude_agent_flag_matches_default(repo):
    payload = {"session_id": "s1", "cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "git push"}}
    assert hook(None, payload, argv=["--agent", "claude", "pre-bash"]) == hook("pre-bash", payload)
    assert hook(None, payload, argv=["--agent=claude", "pre-bash"]) == hook("pre-bash", payload)


def test_every_metrics_event_names_the_agent(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "exit 1"}]})
    session_start(repo)
    bash(repo, "git push")
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    stop(repo)
    events = metrics(repo)
    assert {e["kind"] for e in events} >= {"pre-bash:ask", "stop:block"}
    assert all(e["agent"] == "claude" for e in events)


def test_hooks_json_wires_the_claude_dialect():
    wiring = json.loads((ENGINE.parent / "hooks.json").read_text())
    commands = [h["command"] for groups in wiring["hooks"].values() for g in groups for h in g["hooks"]
                if "/hooks/run" in h["command"]]
    assert commands and all("--agent claude" in c for c in commands)
