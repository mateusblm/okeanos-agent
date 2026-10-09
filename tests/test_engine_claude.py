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
HANDOFF = "[Okeanos] precisa de você"
OLD_HANDOFF = "**Okeanos** · precisa de você"  # sessions mid-flight still use it
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


def edit(root, tool, tool_input, event="pre-edit", session="s1", **kw):
    name = "PreToolUse" if event == "pre-edit" else "PostToolUse"
    return hook(event, {"session_id": session, "cwd": str(root), "hook_event_name": name,
                        "tool_name": tool, "tool_input": tool_input}, **kw)


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


def test_old_handoff_line_is_still_accepted(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo, last="Preciso que você decida.\n\n" + OLD_HANDOFF)
    assert code == 0
    assert set(out) == {"systemMessage"} and "decisão sua" in out["systemMessage"]
    assert "stop:handoff" in [e["kind"] for e in metrics(repo)]


def test_block_asks_for_the_new_handoff_line_only(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    code, out = stop(repo)
    assert out["decision"] == "block"
    assert f"`{HANDOFF}`" in out["reason"] and OLD_HANDOFF not in out["reason"]


def test_hook_messages_start_with_the_okeanos_prefix(repo):
    assert decision(bash(repo, "git push origin feature")[1])[1].startswith("[Okeanos] G2: publicar (git push)")
    assert decision(bash(repo, "git push --force origin feature")[1])[1].startswith("[Okeanos] force push")
    assert decision(bash(repo, "rm -rf /opt/somewhere/else")[1])[1].startswith("[Okeanos] `rm -r` fora")
    assert decision(bash(repo, "okeanos aprovar push")[1])[1].startswith("[Okeanos] aprovações são do humano")
    payload = {"session_id": "s1", "cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": "oi"}
    context = hook("prompt", payload)[1]["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("[Okeanos] antes de agir") and "([Okeanos] rota: <Direto|" in context
    assert "**Okeanos**" not in context
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "echo FAILED; exit 1"}]})
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "# changed\n")
    assert stop(repo)[1]["reason"].startswith("[Okeanos] definição de pronto: corrija antes de encerrar")
    assert stop(repo, last=HANDOFF)[1]["systemMessage"].startswith("[Okeanos] o agente parou")


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


# ---------------------------------------------------------------------------
# approvals: `okeanos aprovar <alvo>` turns one ask into allow, for a while
# ---------------------------------------------------------------------------

NOW = 1_800_000_000
CLOCK = {"OKEANOS_NOW": str(NOW)}


def approve(root, *targets, expires_at=NOW + 600):
    """Write approvals the way `okeanos aprovar` stores them (the on-disk contract)."""
    path = root / ".git" / "okeanos" / "approvals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    for t in targets:
        data[t] = {"approved_at": NOW, "expires_at": expires_at}
    path.write_text(json.dumps(data))


def change_assertion(root):
    return edit(root, "Edit", {"file_path": str(root / "tests" / "test_calc.py"),
                               "old_string": "    assert add(1, 2) == 3", "new_string": "    assert add(1, 2) == 4"},
                env=CLOCK)


def test_ask_tells_how_to_approve_the_exact_target(repo):
    d, reason = decision(change_assertion(repo)[1])
    assert d == "ask"
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"
    d, reason = decision(bash(repo, "git push", env=CLOCK)[1])
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar push"


def test_approved_test_edit_is_allowed_and_logged(repo):
    approve(repo, "tests/test_calc.py")
    assert change_assertion(repo) == (0, None)
    assert "pre-edit:approved" in [e["kind"] for e in metrics(repo)]


def test_expired_approval_asks(repo):
    approve(repo, "tests/test_calc.py", expires_at=NOW - 1)
    assert decision(change_assertion(repo)[1])[0] == "ask"


def test_approval_for_another_file_asks(repo):
    approve(repo, "tests/test_other.py", "push")
    assert decision(change_assertion(repo)[1])[0] == "ask"


def test_approved_shell_write_to_committed_test_is_allowed(repo):
    approve(repo, "tests/test_calc.py")
    assert bash(repo, "echo 'def test_x(): pass' > tests/test_calc.py", env=CLOCK) == (0, None)


def test_approved_push_is_allowed_and_logged(repo):
    approve(repo, "push")
    assert bash(repo, "git push origin feature", env=CLOCK) == (0, None)
    assert bash(repo, "gh pr create --fill", env=CLOCK) == (0, None)
    assert "pre-bash:approved" in [e["kind"] for e in metrics(repo)]


def test_approved_push_does_not_cover_force_push(repo):
    approve(repo, "push")
    assert decision(bash(repo, "git push --force", env=CLOCK)[1])[0] == "deny"


def test_push_approval_does_not_cover_other_asks_in_the_same_command(repo):
    approve(repo, "push")
    d, reason = decision(bash(repo, "echo x > tests/test_calc.py && git push", env=CLOCK)[1])
    assert d == "ask"
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar tests/test_calc.py"


def test_approved_suspicious_package_is_allowed(repo, registry):
    env = registry({
        "https://registry.npmjs.org/expresss": {"time": {"created": "2015-01-01T00:00:00Z"}},
        "https://api.npmjs.org/downloads/point/last-week/expresss": {"downloads": 50000},
    })
    d, reason = decision(bash(repo, "npm install expresss", env={**env, **CLOCK})[1])
    assert reason.splitlines()[-1] == "Para aprovar: okeanos aprovar pacote:expresss"
    approve(repo, "pacote:expresss")
    assert bash(repo, "npm install expresss", env={**env, **CLOCK}) == (0, None)


def test_approval_never_covers_a_nonexistent_package(repo, registry):
    env = registry({"https://registry.npmjs.org/leftpad-hallucinated": 404})
    approve(repo, "pacote:leftpad-hallucinated")
    assert decision(bash(repo, "npm install leftpad-hallucinated", env={**env, **CLOCK})[1])[0] == "deny"


def test_secret_commit_is_denied_whatever_was_approved(repo):
    (repo / "config.py").write_text('KEY = "AKIA' + "ABCDEFGHIJKLMNOP" + '"\n')
    git(repo, "add", "config.py")
    approve(repo, "push", "config.py", "tests/test_calc.py", "pacote:x")
    assert decision(bash(repo, "git commit -m wip", env=CLOCK)[1])[0] == "deny"


# ---------------------------------------------------------------------------
# approvals belong to the human: the agent can't grant them to itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "okeanos aprovar push",
    "okeanos revogar",
    "bin/okeanos aprovar tests/test_calc.py",
    "python3 /opt/okeanos-agent/bin/okeanos aprovar push",
    "cd /tmp && OKEANOS_NOW=1 ~/.local/bin/okeanos aprovar push",
    "sh -c 'okeanos aprovar push'",
    "script -qc 'okeanos aprovar push' /dev/null",
    "echo 'okeanos aprovar push' | script -q /dev/null",
    "x=$(okeanos aprovar push)",
])
def test_agent_running_okeanos_aprovar_is_denied(repo, command):
    d, reason = decision(bash(repo, command)[1])
    assert d == "deny" and "humano" in reason


@pytest.mark.parametrize("command", [
    "okeanos codex-confiar",
    "okeanos codex-confiar --project --sim",
    "bin/okeanos codex-confiar --sim",
    "sh -c 'okeanos codex-confiar --sim'",
])
def test_agent_trusting_codex_hooks_is_denied(repo, command):
    d, reason = decision(bash(repo, command)[1])
    assert d == "deny" and "humano" in reason


def test_agent_running_okeanos_aprovar_outside_a_repo_is_denied(tmp_path):
    out = hook("pre-bash", {"session_id": "s1", "cwd": str(tmp_path), "tool_name": "Bash",
                            "tool_input": {"command": "okeanos aprovar push"}})[1]
    assert decision(out)[0] == "deny"


@pytest.mark.parametrize("command", [
    "okeanos aprovacoes",
    "okeanos metrics 30",
    "okeanos doctor",
    "git commit -m 'docs: explain okeanos aprovar'",
    "git commit -m 'docs: o estado fica em .git/okeanos/approvals.json'",
])
def test_reading_commands_are_allowed(repo, command):
    assert bash(repo, command) == (0, None)


@pytest.mark.parametrize("command", [
    # a project path containing "okeanos", a runner (timeout/env) and the word "aprovar" far away
    "cd /home/u/okeanos-codex-e2e && timeout 60 codex exec 'muda o limite' && grep -n 'Para aprovar' log.txt",
    "cd ~/okeanos-demo && env FOO=1 npm test && echo 'falta aprovar o PR'",
])
def test_okeanos_and_aprovar_far_apart_are_not_self_approval(repo, command):
    assert bash(repo, command) == (0, None), command


@pytest.mark.parametrize("command", [
    "echo '{\"push\": {\"expires_at\": 9999999999}}' > .git/okeanos/approvals.json",
    "cat x >> .git/okeanos/approvals.json",
    "cp /tmp/x .git/okeanos/approvals.json",
    "tee .git/okeanos/approvals.json < /tmp/x",
    "rm .git/okeanos/metrics.jsonl",
    "python3 -c 'open(\".git/okeanos/approvals.json\", \"w\").write(\"{}\")'",
])
def test_agent_writing_okeanos_state_via_shell_is_denied(repo, command):
    d, reason = decision(bash(repo, command)[1])
    assert d == "deny" and "humano" in reason


def test_agent_writing_okeanos_state_from_a_subdirectory_is_denied(repo):
    out = hook("pre-bash", {"session_id": "s1", "cwd": str(repo / "src"), "tool_name": "Bash",
                            "tool_input": {"command": "echo {} > ../.git/okeanos/approvals.json"}})[1]
    assert decision(out)[0] == "deny"


def test_reading_okeanos_state_is_allowed(repo):
    assert bash(repo, "cat .git/okeanos/approvals.json") == (0, None)


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"content": "{}"}),
    ("Edit", {"old_string": "{}", "new_string": "{\"push\": {}}"}),
])
def test_agent_editing_okeanos_state_is_denied(repo, tool, tool_input):
    path = repo / ".git" / "okeanos" / "approvals.json"
    d, reason = decision(edit(repo, tool, {"file_path": str(path), **tool_input})[1])
    assert d == "deny" and "humano" in reason


# ---------------------------------------------------------------------------
# git hooks belong to the human too: the agent can't remove or bypass them
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "okeanos githooks --uninstall",
    "bin/okeanos githooks --uninstall",
    "rm .git/hooks/pre-commit",
    "chmod -x .git/hooks/pre-push",
    "echo exit 0 > .git/hooks/pre-commit",
    "git config core.hooksPath /dev/null",
    "git -c core.hooksPath=/dev/null commit -m x",
])
def test_agent_cannot_remove_or_bypass_git_hooks(repo, command):
    code, out = bash(repo, command)
    action, reason = decision(out)
    assert action == "deny", command
    assert "humano" in reason


@pytest.mark.parametrize("command", [
    "okeanos githooks",
    "cat .git/hooks/pre-commit",
    "ls .git/hooks",
    "git config --get core.hooksPath",
])
def test_reading_or_installing_git_hooks_is_allowed(repo, command):
    assert bash(repo, command) == (0, None), command


def test_agent_cannot_edit_git_hooks_with_the_editor(repo):
    code, out = edit(repo, "Write", {"file_path": str(repo / ".git" / "hooks" / "pre-commit"), "content": "exit 0\n"})
    action, _ = decision(out)
    assert action == "deny"


# ---------------------------------------------------------------------------
# self-approval through an interpreter, a pseudo-terminal or a cleaned environment
# ---------------------------------------------------------------------------

PTY_REPRO = "env -u CLAUDECODE python3 -c \"import pty; pty.spawn(['/path/bin/okeanos','aprovar','push'])\""
NODE_APPROVAL = ("node -e \"require('child_process').spawnSync('/path/bin/okeanos', ['aprovar', 'push'], "
                 "{stdio: 'inherit'})\"")
PERL_APPROVAL = "perl -e 'exec(\"/path/bin/okeanos\", \"aprovar\", \"push\")'"
SCRIPT_LIST_APPROVAL = ("script -qc \"python3 -c \\\"import subprocess; subprocess.run(['okeanos', 'aprovar', "
                        "'push'])\\\"\" /dev/null")
FAR_APART = [
    "cd /home/u/okeanos-codex-e2e && timeout 60 codex exec 'muda o limite' && grep -n 'Para aprovar' log.txt",
    "cd ~/okeanos-demo && env FOO=1 npm test && echo 'falta aprovar o PR'",
    "cd /home/u/okeanos-demo && python3 -m pytest -q -k aprovar",
    "cd ~/okeanos-demo && node -e 'console.log(1)' && echo 'falta aprovar o PR'",
    "cd /home/u/okeanos-demo && python3 -c \"import pty; pty.spawn(['npm', 'test'])\"",
]


@pytest.mark.parametrize("command", [
    PTY_REPRO,
    "python3 -c \"import pty; pty.spawn(['/path/bin/okeanos', 'aprovar', 'push'])\"",
    NODE_APPROVAL,
    PERL_APPROVAL,
    "ruby -e 'system(\"okeanos\", \"revogar\")'",
    SCRIPT_LIST_APPROVAL,
    "python3 -c \"import pty,sys; pty.spawn(sys.argv[1:])\" bin/okeanos aprovar push",
    "python3 -c \"from okeanos_engine import user_cli; user_cli.main(['aprovar', 'push'])\"",
    "python3 -c \"import os, pty; os.environ.pop('CLAUDECODE'); pty.spawn(['okeanos', 'apro' + 'var', 'push'])\"",
    "python3 - <<'EOF'\nimport pty\npty.spawn(['okeanos', 'aprovar', 'push'])\nEOF",
    "socat - \"EXEC:/path/bin/okeanos aprovar push\",pty,setsid",
    "tmux new-session -d '/path/bin/okeanos aprovar push'",
    "echo aprovar push | xargs okeanos",
    "unset CLAUDECODE CODEX_THREAD_ID && script -q /dev/null bin/okeanos",
    "env -u CODEX_THREAD_ID -u CODEX_SESSION_ID bin/okeanos doctor",
    "CLAUDECODE= python3 hooks/okeanos.py",
])
def test_agent_approving_through_an_interpreter_or_pty_is_denied(repo, command):
    d, reason = decision(bash(repo, command)[1])
    assert d == "deny" and "humano" in reason, command


@pytest.mark.parametrize("command", FAR_APART + [
    "script -q /dev/null npm test",
    "env -u FOO okeanos doctor",
    "python3 -m pytest -q tests/test_user_cli.py -k aprovar",
    "git commit -m 'rules: deny bin/okeanos under pty.spawn'",
    "grep -rn 'pty.spawn' hooks/okeanos.py",
])
def test_interpreters_and_ptys_without_the_okeanos_cli_are_allowed(repo, command):
    assert bash(repo, command) == (0, None), command


# ---------------------------------------------------------------------------
# the TMPDIR fallback state belongs to the human too
# ---------------------------------------------------------------------------

@pytest.fixture
def tmpdir_env(tmp_path):
    d = tmp_path / "tmp"
    d.mkdir()
    return d, {"TMPDIR": str(d)}


@pytest.mark.parametrize("command", [
    "echo '{}' > {tmp}/okeanos/0123456789abcdef/sessions/s1.json",
    "rm -rf {tmp}/okeanos",
    "rm -rf /tmp/okeanos/0123456789abcdef",
    "python3 -c \"import shutil; shutil.rmtree('{tmp}/okeanos')\"",
    "sed -i 's/1/2/' {tmp}/okeanos/0123456789abcdef/metrics.jsonl",
])
def test_agent_writing_fallback_state_is_denied(repo, tmpdir_env, command):
    tmp, env = tmpdir_env
    d, reason = decision(bash(repo, command.replace("{tmp}", str(tmp)), env=env)[1])
    assert d == "deny" and "humano" in reason, command


@pytest.mark.parametrize("command", [
    "cat {tmp}/okeanos/0123456789abcdef/metrics.jsonl",
    "rm -rf /tmp/okeanos-build",
    "ls /tmp/okeanos-neutral-abc",
])
def test_reading_fallback_state_and_lookalike_paths_are_allowed(repo, tmpdir_env, command):
    tmp, env = tmpdir_env
    assert bash(repo, command.replace("{tmp}", str(tmp)), env=env) == (0, None), command


def test_agent_editing_fallback_state_is_denied(repo, tmpdir_env):
    tmp, env = tmpdir_env
    path = tmp / "okeanos" / "0123456789abcdef" / "sessions" / "s1.json"
    d, reason = decision(edit(repo, "Write", {"file_path": str(path), "content": "{}"}, env=env)[1])
    assert d == "deny" and "humano" in reason


# ---------------------------------------------------------------------------
# project hook files with Okeanos entries, and `okeanos install --uninstall`
# ---------------------------------------------------------------------------

HOOK_FILES = {
    ".codex/hooks.json": '{"hooks": {"PreToolUse": [{"hooks": [{"command": "/x/okeanos/hooks/run --agent codex pre-tool"}]}]}}\n',
    ".cursor/hooks.json": '{"hooks": {"stop": [{"command": "/x/okeanos/hooks/run --agent cursor stop"}]}}\n',
    ".cursor/rules/okeanos.mdc": "---\ndescription: Processo Okeanos\n---\n# Okeanos\n",
    ".github/hooks/okeanos.json": '{"hooks": {"agentStop": [{"bash": "/x/okeanos/hooks/run --agent copilot stop"}]}}\n',
}


@pytest.fixture
def hooked_repo(repo):
    for rel, text in HOOK_FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    return repo


@pytest.mark.parametrize("command", [
    "rm .codex/hooks.json",
    "mv .codex/hooks.json /tmp/x.json",
    "echo '{}' > .codex/hooks.json",
    "chmod 000 .cursor/hooks.json",
    "sed -i 's/okeanos//' .cursor/rules/okeanos.mdc",
    "rm -rf .github/hooks",
    "rm -rf .codex",
    "python3 -c \"import os; os.remove('.codex/hooks.json')\"",
    "okeanos install --uninstall",
    "okeanos install --agent codex --uninstall",
    "bin/okeanos install --agent cursor --project --uninstall",
    "sh -c 'okeanos install --agent codex --project --uninstall'",
])
def test_agent_cannot_remove_project_hooks_or_uninstall(hooked_repo, command):
    d, reason = decision(bash(hooked_repo, command)[1])
    assert d == "deny" and "humano" in reason, command


@pytest.mark.parametrize("command", [
    "cat .codex/hooks.json",
    "jq . .cursor/hooks.json",
    "git add .codex/hooks.json .github/hooks/okeanos.json",
    "okeanos install --agent codex --project",
    "okeanos install --dry-run",
])
def test_reading_project_hooks_and_installing_are_allowed(hooked_repo, command):
    assert bash(hooked_repo, command) == (0, None), command


def test_hook_files_without_okeanos_are_free(repo):
    (repo / ".codex").mkdir()
    (repo / ".codex" / "hooks.json").write_text('{"hooks": {}}\n')
    assert bash(repo, "rm .codex/hooks.json") == (0, None)
    assert bash(repo, "echo '{}' > .cursor/hooks.json") == (0, None)


@pytest.mark.parametrize("rel", sorted(HOOK_FILES))
def test_agent_cannot_edit_project_hooks_with_the_editor(hooked_repo, rel):
    d, reason = decision(edit(hooked_repo, "Write", {"file_path": str(hooked_repo / rel), "content": "{}"})[1])
    assert d == "deny" and "humano" in reason, rel


# ---------------------------------------------------------------------------
# the committed checks.json is the ruler: loosening it needs the user's approval
# ---------------------------------------------------------------------------

RULER = "docs/agents/checks.json"
RULER_TEXT = """{
  "onDone": [
    {"name": "tests", "cmd": "python3 -m pytest -q", "timeout": 600},
    {"name": "lint", "cmd": "ruff check ."}
  ],
  "onEdit": [
    {"name": "fmt", "cmd": "ruff format {file}", "ext": [".py"]}
  ],
  "maxChangedLines": 400,
  "testPatterns": ["(^|/)checks/"]
}
"""


def commit_ruler(root, text=RULER_TEXT):
    (root / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    (root / RULER).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "ruler")
    return root


@pytest.fixture
def ruled(repo):
    return commit_ruler(repo)


def ruler_edit(root, old, new, **kw):
    return edit(root, "Edit", {"file_path": str(root / RULER), "old_string": old, "new_string": new}, **kw)


def ruler_write(root, content, **kw):
    if not isinstance(content, str):
        content = json.dumps(content, indent=2)
    return edit(root, "Write", {"file_path": str(root / RULER), "content": content}, **kw)


def ruler(**changes):
    data = json.loads(RULER_TEXT)
    for key, value in changes.items():
        if value is None:
            data.pop(key)
        else:
            data[key] = value
    return data


def asks_for_ruler(out):
    d, reason = decision(out)
    assert d == "ask", reason
    assert RULER in reason
    assert reason.splitlines()[-1] == f"Para aprovar: okeanos aprovar {RULER}"
    return reason


def test_changing_a_done_command_asks(ruled):
    asks_for_ruler(ruler_edit(ruled, '"cmd": "python3 -m pytest -q"', '"cmd": "true"')[1])
    assert "pre-edit:ask" in [e["kind"] for e in metrics(ruled)]


def test_raising_max_changed_lines_asks(ruled):
    asks_for_ruler(ruler_edit(ruled, '"maxChangedLines": 400', '"maxChangedLines": 2000')[1])


def test_lowering_max_changed_lines_is_allowed(ruled):
    assert ruler_edit(ruled, '"maxChangedLines": 400', '"maxChangedLines": 200') == (0, None)


def test_adding_a_done_command_is_allowed(ruled):
    assert edit(ruled, "MultiEdit", {"file_path": str(ruled / RULER), "edits": [
        {"old_string": '"onDone": [\n', "new_string": '"onDone": [\n    {"name": "types", "cmd": "mypy ."},\n'},
        {"old_string": '"onEdit": [\n', "new_string": '"onEdit": [\n    {"name": "lint", "cmd": "ruff check {file}"},\n'},
    ]}) == (0, None)


def test_multiedit_removing_a_done_command_asks(ruled):
    asks_for_ruler(edit(ruled, "MultiEdit", {"file_path": str(ruled / RULER), "edits": [
        {"old_string": '"onEdit": [\n', "new_string": '"onEdit": [\n    {"name": "lint", "cmd": "ruff check {file}"},\n'},
        {"old_string": ',\n    {"name": "lint", "cmd": "ruff check ."}\n  ],', "new_string": "\n  ],"},
    ]})[1])


@pytest.mark.parametrize("content", [
    ruler(onDone=[{"name": "tests", "cmd": "python3 -m pytest -q", "timeout": 600}]),
    ruler(onDone=None),
    ruler(onEdit=[{"name": "fmt", "cmd": "ruff format {file}", "ext": [".py", ".pyi"]}]),
    ruler(onDone=[{"name": "tests", "cmd": "python3 -m pytest -q", "timeout": 5}, {"name": "lint", "cmd": "ruff check ."}]),
    ruler(maxChangedLines=None),
    ruler(maxChangedLines="9999"),
    ruler(testPatterns=[]),
    "{ not json",
    "",
    "[]",
], ids=["remove-done", "drop-done", "change-ext", "change-timeout", "drop-limit", "limit-as-string",
        "remove-test-pattern", "invalid", "empty", "not-an-object"])
def test_writing_a_looser_ruler_asks(ruled, content):
    asks_for_ruler(ruler_write(ruled, content)[1])


@pytest.mark.parametrize("content", [
    ruler(testPatterns=["(^|/)checks/", "_check\\.py$"], maxChangedLines=300),
    ruler(onDone=[{"name": "lint", "cmd": "ruff check ."},
                  {"name": "pytest", "cmd": "python3 -m pytest -q", "timeout": 600}]),
    ruler(extra={"note": "unknown keys are not the ruler"}),
], ids=["tighten", "reorder-and-rename", "unknown-key"])
def test_writing_an_equal_or_stricter_ruler_is_allowed(ruled, content):
    assert ruler_write(ruled, content) == (0, None)


def test_raising_the_default_limit_asks(repo):
    commit_ruler(repo, json.dumps({"onDone": []}, indent=2))
    asks_for_ruler(ruler_write(repo, {"onDone": [], "maxChangedLines": 1000})[1])
    assert ruler_write(repo, {"onDone": [], "maxChangedLines": 300}) == (0, None)


def test_edit_that_cannot_be_applied_asks(ruled):
    asks_for_ruler(ruler_edit(ruled, '"cmd": "not in the file"', '"cmd": "true"')[1])


@pytest.mark.parametrize("command", [
    "echo {} > docs/agents/checks.json",
    "cat /tmp/x >> docs/agents/checks.json",
    "rm docs/agents/checks.json",
    "rm -f ./docs/agents/checks.json",
    "sed -i 's/400/4000/' docs/agents/checks.json",
    "mv docs/agents/checks.json /tmp/checks.json",
    "mv /tmp/looser.json docs/agents/checks.json",
    "cp /tmp/looser.json docs/agents/checks.json",
    "jq '.maxChangedLines = 9999' docs/agents/checks.json | tee docs/agents/checks.json",
    "truncate -s 0 docs/agents/checks.json",
    "git rm docs/agents/checks.json",
    "git mv docs/agents/checks.json docs/agents/old.json",
])
def test_shell_writing_the_ruler_asks(ruled, command):
    asks_for_ruler(bash(ruled, command)[1])


def test_shell_writing_the_ruler_from_a_subdirectory_asks(ruled):
    out = hook("pre-bash", {"session_id": "s1", "cwd": str(ruled / "docs"), "hook_event_name": "PreToolUse",
                            "tool_name": "Bash", "tool_input": {"command": "echo {} > agents/checks.json"}})[1]
    asks_for_ruler(out)


@pytest.mark.parametrize("command", [
    "cat docs/agents/checks.json",
    "jq . docs/agents/checks.json",
    "git diff docs/agents/checks.json",
    "echo {} > docs/agents/other.json",
])
def test_reading_the_ruler_is_allowed(ruled, command):
    assert bash(ruled, command) == (0, None), command


def test_uncommitted_ruler_is_free(repo):
    (repo / "docs" / "agents").mkdir(parents=True)
    (repo / RULER).write_text(RULER_TEXT)
    assert ruler_write(repo, {"onDone": []}) == (0, None)
    assert ruler_edit(repo, '"maxChangedLines": 400', '"maxChangedLines": 2000') == (0, None)
    assert bash(repo, "echo {} > docs/agents/checks.json") == (0, None)
    assert bash(repo, "rm docs/agents/checks.json") == (0, None)


def test_approved_ruler_change_is_allowed(ruled):
    approve(ruled, RULER)
    assert ruler_edit(ruled, '"maxChangedLines": 400', '"maxChangedLines": 2000', env=CLOCK) == (0, None)
    assert ruler_write(ruled, "{}", env=CLOCK) == (0, None)
    assert bash(ruled, "rm docs/agents/checks.json", env=CLOCK) == (0, None)
    assert "pre-edit:approved" in [e["kind"] for e in metrics(ruled)]


def test_ruler_approval_does_not_cover_tests(ruled):
    approve(ruled, RULER)
    d, _ = decision(change_assertion(ruled)[1])
    assert d == "ask"


# ---------------------------------------------------------------------------
# stop: loosened quality configs, stubs and empty catches are told to the user once
# ---------------------------------------------------------------------------

def commit_files(root, files):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "configs")


def quality_message(out):
    """The stop notice: a message to the user that never blocks the turn end."""
    assert out is not None, "expected a stop notice"
    assert set(out) == {"systemMessage"}, out
    message = out["systemMessage"]
    assert message.startswith("[Okeanos] ")
    return message


def warns_once(root, *expected):
    message = quality_message(stop(root)[1])
    for text in expected:
        assert text in message, message
    assert stop(root) == (0, None)
    return message


LOOSENED_CONFIGS = [
    ("tsconfig.json", '{\n  "compilerOptions": {\n    "strict": true,\n    "target": "es2022"\n  }\n}\n',
     '{\n  "compilerOptions": {\n    "strict": false,\n    "target": "es2022"\n  }\n}\n', "`strict` desligado"),
    ("tsconfig.base.json", '{\n  "compilerOptions": {\n    "noImplicitAny": true,\n    "target": "es2022"\n  }\n}\n',
     '{\n  "compilerOptions": {\n    "target": "es2022"\n  }\n}\n', "`noImplicitAny: true` removido"),
    (".eslintrc.json", '{\n  "rules": {\n    "no-console": "error"\n  }\n}\n',
     '{\n  "rules": {\n    "no-console": "off"\n  }\n}\n', "regra `no-console` desligada"),
    ("eslint.config.js", "export default [{\n  rules: {\n    'no-unused-vars': 2,\n  },\n}];\n",
     "export default [{\n  rules: {\n    'no-unused-vars': 0,\n  },\n}];\n", "regra `no-unused-vars` desligada"),
    ("package.json", '{\n  "scripts": {\n    "lint": "eslint . --max-warnings 0"\n  }\n}\n',
     '{\n  "scripts": {\n    "lint": "eslint . --max-warnings 25"\n  }\n}\n', "`--max-warnings` subiu de 0 para 25"),
    ("pyproject.toml", "[tool.mypy]\nstrict = true\n", "[tool.mypy]\nstrict = false\n", "`strict` desligado"),
    ("mypy.ini", "[mypy]\ndisallow_untyped_defs = True\n", "[mypy]\ndisallow_untyped_defs = False\n",
     "`disallow_untyped_defs` desligado"),
    ("setup.cfg", "[flake8]\nextend-ignore =\n    E203\n", "[flake8]\nextend-ignore =\n    E203\n    E501\n",
     "lista de ignore cresce: E501"),
    ("pyproject.toml", '[tool.ruff.lint]\nignore = ["E501"]\n', '[tool.ruff.lint]\nignore = ["E501", "F401"]\n',
     "lista de ignore cresce: F401"),
    ("pyproject.toml", "[tool.coverage.report]\nfail_under = 90\n", "[tool.coverage.report]\nfail_under = 75\n",
     "`fail_under` baixou de 90 para 75"),
    ("Makefile", "test:\n\tpytest --cov=src --cov-fail-under=85\n", "test:\n\tpytest --cov=src --cov-fail-under=50\n",
     "`fail_under` baixou de 85 para 50"),
    ("jest.config.js", "module.exports = {\n  coverageThreshold: {\n    global: {\n      lines: 80,\n    },\n  },\n};\n",
     "module.exports = {\n  coverageThreshold: {\n    global: {\n      lines: 60,\n    },\n  },\n};\n",
     "cobertura `lines` baixou de 80 para 60"),
]


@pytest.mark.parametrize("rel,before,after,expected", LOOSENED_CONFIGS,
                         ids=[f"{c[0]}:{c[3]}" for c in LOOSENED_CONFIGS])
def test_loosened_quality_config_warns_once_without_blocking(repo, rel, before, after, expected):
    commit_files(repo, {rel: before})
    session_start(repo)
    (repo / rel).write_text(after)
    warns_once(repo, rel, expected)
    assert "stop:quality" in [e["kind"] for e in metrics(repo)]


TIGHTENED_CONFIGS = [
    ("tsconfig.json", '{\n  "compilerOptions": {\n    "strict": false\n  }\n}\n',
     '{\n  "compilerOptions": {\n    "strict": true\n  }\n}\n'),
    (".eslintrc.json", '{\n  "rules": {\n    "no-console": "off"\n  }\n}\n',
     '{\n  "rules": {\n    "no-console": "error"\n  }\n}\n'),
    ("package.json", '{\n  "scripts": {\n    "lint": "eslint . --max-warnings 10"\n  }\n}\n',
     '{\n  "scripts": {\n    "lint": "eslint src --max-warnings 0"\n  }\n}\n'),
    ("setup.cfg", "[flake8]\nextend-ignore =\n    E203\n    E501\n", "[flake8]\nextend-ignore =\n    E203\n"),
    ("pyproject.toml", "[tool.coverage.report]\nfail_under = 75\n", "[tool.coverage.report]\nfail_under = 90\n"),
    ("pyproject.toml", '[tool.ruff.lint]\nselect = ["E"]\n', '[tool.ruff.lint]\nselect = ["E", "F", "B"]\n'),
    ("src/settings.json", '{\n  "strict": true\n}\n', '{\n  "strict": false\n}\n'),  # not a quality config
]


@pytest.mark.parametrize("rel,before,after", TIGHTENED_CONFIGS, ids=[c[0] for c in TIGHTENED_CONFIGS])
def test_tightened_or_unrelated_config_is_silent(repo, rel, before, after):
    commit_files(repo, {rel: before})
    session_start(repo)
    (repo / rel).write_text(after)
    assert stop(repo) == (0, None)


def test_loosened_checks_json_during_the_session_warns_once(ruled):
    session_start(ruled)
    # written behind the editor's back (an interpreter, git checkout of an old version)
    (ruled / RULER).write_text(json.dumps(ruler(maxChangedLines=5000), indent=2))
    warns_once(ruled, RULER, "maxChangedLines sobe de 400 para 5000")


def test_deleted_checks_json_warns(ruled):
    session_start(ruled)
    (ruled / RULER).unlink()
    warns_once(ruled, RULER, "apagado")


def test_tightened_checks_json_is_silent(ruled):
    session_start(ruled)
    (ruled / RULER).write_text(json.dumps(ruler(maxChangedLines=200), indent=2))
    assert stop(ruled) == (0, None)


STUBS = [
    ("src/a.py", "def load(path):\n    raise NotImplementedError\n", "stub"),
    ("src/a.py", "def load(path):\n    # TODO: implement\n    return None\n", "stub"),
    ("src/a.ts", "export function load(): string {\n  throw new Error('Not implemented');\n}\n", "stub"),
    ("src/lib.rs", "pub fn load() -> u8 {\n    todo!()\n}\n", "stub"),
    ("src/lib.rs", "pub fn load() -> u8 {\n    unimplemented!(\"later\")\n}\n", "stub"),
    ("src/a.go", "package a\n\nfunc Load() int {\n\tpanic(\"not implemented\")\n}\n", "stub"),
    ("src/a.py", "def load(path):\n    pass\n", "`pass` como corpo único de `load`"),
    ("src/a.py", "def load(path): pass\n", "`pass` como corpo único de `load`"),
    ("src/a.ts", "export function load() {\n  try { run(); } catch (e) {}\n}\n", "catch vazio"),
    ("src/a.ts", "export function load() {\n  try {\n    run();\n  } catch {\n  }\n}\n", "catch vazio"),
    ("src/a.py", "def load():\n    try:\n        run()\n    except ValueError:\n        pass\n    return 1\n", "except vazio"),
    ("src/a.py", "def load():\n    try:\n        run()\n    except: pass\n", "except vazio"),
]


@pytest.mark.parametrize("rel,code,expected", STUBS, ids=[f"{s[0]}:{i}" for i, s in enumerate(STUBS)])
def test_new_stub_or_empty_catch_warns_once_without_blocking(repo, rel, code, expected):
    session_start(repo)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(code)
    warns_once(repo, rel, expected)


def test_stub_added_to_a_tracked_file_warns(repo):
    session_start(repo)
    (repo / "src" / "calc.py").write_text(SRC_FILE + "\n\ndef sub(a, b):\n    raise NotImplementedError\n")
    warns_once(repo, "src/calc.py", "NotImplementedError")


NOT_STUBS = [
    ("tests/test_load.py", "def test_load():\n    pass\n"),  # tests may stub
    ("src/load.test.ts", "it('loads', () => {\n  try { run(); } catch (e) {}\n});\n"),
    ("src/a.py", "from abc import abstractmethod\n\n\nclass A:\n    @abstractmethod\n    def load(self):\n        pass\n"),
    ("src/a.py", "def load(path):\n    pass\n    return path\n"),
    ("src/a.py", "def load():\n    try:\n        run()\n    except ValueError:\n        log()\n"),
    ("src/a.py", "def load():\n    try:\n        run()\n    except ValueError:\n        # optional dependency\n        pass\n"),
    ("src/a.ts", "export function load() {\n  try { run(); } catch (e) { log(e); }\n}\n"),
    ("src/a.ts", "export function load() {\n  try {\n    run();\n  } catch {\n    // best effort\n  }\n}\n"),
    ("src/a.py", "def load(path):\n    # TODO: implementation notes live in docs\n    return path\n"),
    ("README.md", "Call `raise NotImplementedError` in abstract methods.\n"),
]


@pytest.mark.parametrize("rel,code", NOT_STUBS, ids=[s[0] + ":" + str(i) for i, s in enumerate(NOT_STUBS)])
def test_code_without_new_stubs_is_silent(repo, rel, code):
    session_start(repo)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(code)
    assert stop(repo) == (0, None)


def test_quality_notice_is_not_repeated_when_the_diff_changes_elsewhere(repo):
    session_start(repo)
    (repo / "src" / "a.py").write_text("def load(path):\n    raise NotImplementedError\n")
    quality_message(stop(repo)[1])
    (repo / "src" / "calc.py").write_text(SRC_FILE + "\n\ndef sub(a, b):\n    return a - b\n")
    assert stop(repo) == (0, None)
    (repo / "src" / "b.py").write_text("def save(path):\n    raise NotImplementedError\n")
    message = quality_message(stop(repo)[1])
    assert "src/b.py" in message and "src/a.py" not in message


def test_quality_notice_waits_for_a_failing_done_and_never_blocks_on_its_own(repo):
    set_checks(repo, {"onDone": [{"name": "tests", "cmd": "test ! -f FAIL"}]})
    session_start(repo)
    (repo / "FAIL").write_text("x\n")
    (repo / "src" / "a.py").write_text("def load(path):\n    raise NotImplementedError\n")
    code, out = stop(repo)
    assert out["decision"] == "block" and "NotImplementedError" not in out["reason"]
    (repo / "FAIL").unlink()
    warns_once(repo, "src/a.py")
