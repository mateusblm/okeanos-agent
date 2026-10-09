"""Consented hook trust for Codex: `okeanos install --agent codex` asks, then trusts the Okeanos hooks
through Codex's own app-server (hooks/list + config/batchWrite), and `okeanos codex-confiar` does that step alone.

A fake `codex` on PATH implements a minimal app-server over stdio JSON-RPC. It builds hooks/list from the
hooks files on disk ($CODEX_HOME/hooks.json and <cwd>/.codex/hooks.json), keeps hooks.state in
$FAKE_STATE/hooks_state.json (standing in for config.toml) and logs every request to $FAKE_STATE/requests.jsonl.
Consent needs a terminal, so the yes/no paths run under a pseudo-TTY; the refusal paths use plain pipes or an
agent-session variable. OKEANOS_HOME_DIR replaces HOME, so the real ~/.codex is never touched.
"""

import json
import os
import pty
import select
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "okeanos"
AGENT_VARS = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI", "CODEX_SANDBOX",
              "CODEX_SANDBOX_NETWORK_DISABLED", "CURSOR_AGENT")
THIRD_PARTY = "/opt/other-tool/hook.sh"

FAKE_CODEX = r'''#!PYTHON
import hashlib, json, os, sys
state_dir = os.environ["FAKE_STATE"]
def path(name): return os.path.join(state_dir, name)
def load(name, default):
    try:
        with open(path(name)) as f: return json.load(f)
    except FileNotFoundError: return default
def save(name, data):
    with open(path(name), "w") as f: json.dump(data, f)
if sys.argv[1:] != ["app-server"]:
    sys.exit(0)
if os.path.exists(path("fail_start")):
    sys.stderr.write("error: not logged in (fake)\n"); sys.exit(1)
codex_home = os.environ.get("CODEX_HOME") or os.path.join(os.environ["HOME"], ".codex")
with open(path("codex_home"), "w") as f: f.write(codex_home)
def snake(ev): return "".join("_" + c.lower() if c.isupper() else c for c in ev).lstrip("_")
def entries(cwd):
    files = [(os.path.join(codex_home, "hooks.json"), "user"), (os.path.join(cwd, ".codex", "hooks.json"), "project")]
    state, out = load("hooks_state.json", {}), []
    for file, source in files:
        try:
            with open(file) as f: data = json.load(f)
        except (FileNotFoundError, ValueError): continue
        for ev, groups in data.get("hooks", {}).items():
            for gi, g in enumerate(groups):
                for hi, h in enumerate(g.get("hooks", [])):
                    key = f"{file}:{snake(ev)}:{gi}:{hi}"
                    digest = "sha256:" + hashlib.sha256(json.dumps([ev, g.get("matcher"), h], sort_keys=True).encode()).hexdigest()
                    trusted = state.get(key, {}).get("trusted_hash")
                    status = "trusted" if trusted == digest else ("modified" if trusted else "untrusted")
                    out.append({"key": key, "eventName": ev[0].lower() + ev[1:], "handlerType": "command",
                                "command": h.get("command"), "matcher": g.get("matcher"), "sourcePath": file,
                                "source": source, "isManaged": False, "enabled": True,
                                "currentHash": digest, "trustStatus": status})
    return out
def reply(i, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": i}
    if error: msg["error"] = {"code": -32600, "message": error}
    else: msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    with open(path("requests.jsonl"), "a") as f: f.write(json.dumps(msg) + "\n")
    method, i, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if i is None: continue
    if method == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "some/notification", "params": {}}) + "\n")
        reply(i, {"userAgent": "fake", "codexHome": codex_home})
    elif method == "hooks/list":
        reply(i, {"data": [{"cwd": c, "hooks": entries(c), "warnings": [], "errors": []} for c in params["cwds"]]})
    elif method == "config/read":
        state = load("hooks_state.json", {})
        reply(i, {"config": {}, "origins": {}, "layers": [
            {"name": {"type": "user", "file": os.path.join(codex_home, "config.toml"), "profile": None},
             "version": "v%d" % load("version.json", 0), "config": {"model": "x", "hooks": {"state": state}}}]})
    elif method == "config/batchWrite":
        if os.path.exists(path("fail_write")):
            reply(i, error="Invalid configuration: hooks.state is read-only here (fake)"); continue
        version = load("version.json", 0)
        if params.get("expectedVersion") not in (None, "v%d" % version):
            reply(i, error="configVersionConflict"); continue
        state = load("hooks_state.json", {})
        for edit in params["edits"]:
            assert edit["keyPath"] == "hooks.state"
            if edit["mergeStrategy"] == "replace": state = dict(edit["value"])
            else: state.update(edit["value"])
        save("hooks_state.json", state); save("version.json", version + 1)
        reply(i, {"status": "ok", "version": "v%d" % (version + 1), "filePath": os.path.join(codex_home, "config.toml")})
    else:
        reply(i, error="unknown method " + str(method))
'''


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "state"
    s.mkdir()
    return s


@pytest.fixture
def fakebin(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir()
    codex = d / "codex"
    codex.write_text(FAKE_CODEX.replace("PYTHON", sys.executable, 1))
    codex.chmod(0o755)
    return d


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def env_for(home, fakebin, state, extra=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OKEANOS_", "CODEX_", "CLAUDE", "COPILOT_", "CURSOR_")) and k != "PATH"}
    env.update({"OKEANOS_HOME_DIR": str(home), "FAKE_STATE": str(state),
                "PATH": os.pathsep.join((str(fakebin), "/usr/bin", "/bin"))})
    env.update(extra or {})
    return env


def run(home, fakebin, state, *args, cwd=None, extra=None):
    """Plain pipes, as an agent's shell or a script would run it."""
    p = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, cwd=cwd or home,
                       env=env_for(home, fakebin, state, extra), stdin=subprocess.DEVNULL, timeout=120)
    return p.returncode, p.stdout + p.stderr


def run_tty(home, fakebin, state, *args, answer=None, cwd=None, extra=None):
    """stdin and stdout on a pseudo-terminal; `answer` is typed when the [s/N] question shows up."""
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, str(CLI), *args], cwd=cwd or home, env=env_for(home, fakebin, state, extra),
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    chunks, answered = [], False
    while True:
        ready, _, _ = select.select([master], [], [], 60)
        if not ready:
            break
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
        if answer is not None and not answered and b"[s/N]" in b"".join(chunks):
            os.write(master, (answer + "\n").encode())
            answered = True
    os.close(master)
    return p.wait(timeout=60), b"".join(chunks).decode(errors="replace")


def requests(state):
    path = state / "requests.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def writes(state):
    return [r["params"] for r in requests(state) if r.get("method") == "config/batchWrite"]


def hooks_state(state):
    path = state / "hooks_state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def is_okeanos(command):
    return str(ROOT) in (command or "") and "--agent codex" in command


def okeanos_keys(hooks_file):
    """Keys the fake Codex gives the Okeanos handlers in hooks_file (its own <file>:<event>:<group>:<handler>)."""
    data = json.loads(hooks_file.read_text())
    snake = lambda ev: "".join("_" + c.lower() if c.isupper() else c for c in ev).lstrip("_")  # noqa: E731
    return {f"{hooks_file}:{snake(ev)}:{gi}:{hi}" for ev, groups in data["hooks"].items()
            for gi, g in enumerate(groups) for hi, h in enumerate(g["hooks"]) if is_okeanos(h.get("command"))}


def with_third_party(hooks_file):
    """A hooks file that already has another tool's hook (before Okeanos is installed)."""
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    hooks_file.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": THIRD_PARTY}]}]}}))
    return f"{hooks_file}:pre_tool_use:0:0"


# ---------------------------------------------------------------------------
# okeanos install --agent codex (user level)
# ---------------------------------------------------------------------------

def test_yes_trusts_only_the_okeanos_hooks_and_verifies(home, fakebin, state):
    hooks_file = home / ".codex" / "hooks.json"
    third = with_third_party(hooks_file)
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "Autorizar esses hooks no Codex agora? [s/N]" in out
    assert "sandbox" in out
    assert f'"{ROOT}/hooks/run" --agent codex pre-tool' in out  # the exact command is shown before asking
    assert (state / "codex_home").read_text() == str(home / ".codex")  # the same Codex home we installed into
    methods = [r.get("method") for r in requests(state)]
    assert methods == ["initialize", "initialized", "hooks/list", "config/batchWrite", "hooks/list"]
    init = requests(state)[0]["params"]
    assert init["clientInfo"]["name"] == "okeanos" and init["clientInfo"]["title"] == "Okeanos"
    [write] = writes(state)
    assert write["reloadUserConfig"] is True
    [edit] = write["edits"]
    assert edit["keyPath"] == "hooks.state" and edit["mergeStrategy"] == "upsert"
    ours = okeanos_keys(hooks_file)
    assert len(ours) == 6 and set(edit["value"]) == ours
    assert third not in hooks_state(state)
    assert all(v["trusted_hash"].startswith("sha256:") for v in edit["value"].values())
    assert out.count("confiado") >= 6 and "PreToolUse" in out


def test_already_trusted_and_modified_are_handled(home, fakebin, state):
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="n")
    keys = sorted(okeanos_keys(home / ".codex" / "hooks.json"))
    # one Okeanos hook changed since it was trusted, the rest were never trusted
    (state / "hooks_state.json").write_text(json.dumps({keys[0]: {"trusted_hash": "sha256:old"}}))
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim")
    assert code == 0, out
    [write] = writes(state)
    assert set(write["edits"][0]["value"]) == set(keys)
    # all trusted now: a second run writes nothing
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim")
    assert code == 0, out
    assert len(writes(state)) == 1
    assert "já" in out


def test_no_writes_nothing_and_says_how_to_do_it_later(home, fakebin, state):
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="n")
    assert code == 0, out
    assert writes(state) == [] and requests(state) == []
    assert "okeanos codex-confiar" in out and "Trust all and continue" in out


def test_empty_answer_defaults_to_no(home, fakebin, state):
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="")
    assert code == 0, out
    assert requests(state) == []


def test_without_a_terminal_nothing_is_written(home, fakebin, state):
    code, out = run(home, fakebin, state, "install", "--agent", "codex")
    assert code == 0, out
    assert (home / ".codex" / "hooks.json").exists()
    assert requests(state) == []
    assert "okeanos codex-confiar" in out and "Trust all and continue" in out


@pytest.mark.parametrize("var", AGENT_VARS)
def test_inside_an_agent_session_trust_is_refused(home, fakebin, state, var):
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s", extra={var: "1"})
    assert code == 0, out
    assert "[s/N]" not in out
    assert requests(state) == []
    assert var in out and "okeanos codex-confiar" in out


def test_app_server_failure_falls_back_to_slash_hooks(home, fakebin, state):
    (state / "fail_start").write_text("")
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "not logged in" in out
    assert "/hooks" in out


def test_rejected_write_is_reported_with_codex_reason(home, fakebin, state):
    (state / "fail_write").write_text("")
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "hooks.state is read-only here" in out and "/hooks" in out
    assert hooks_state(state) == {}


def test_codex_missing_from_path_falls_back(home, fakebin, state, tmp_path):
    (fakebin / "codex").unlink()
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "codex" in out and "/hooks" in out


# ---------------------------------------------------------------------------
# okeanos codex-confiar
# ---------------------------------------------------------------------------

def test_codex_confiar_sim_trusts_without_asking(home, fakebin, state):
    run(home, fakebin, state, "install", "--agent", "codex")
    assert requests(state) == []
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim")
    assert code == 0, out
    assert "[s/N]" not in out
    assert set(writes(state)[0]["edits"][0]["value"]) == okeanos_keys(home / ".codex" / "hooks.json")


def test_codex_confiar_asks_without_sim(home, fakebin, state):
    run(home, fakebin, state, "install", "--agent", "codex")
    code, out = run_tty(home, fakebin, state, "codex-confiar", answer="n")
    assert code == 0, out
    assert "[s/N]" in out and requests(state) == []


def test_codex_confiar_sim_still_needs_a_terminal(home, fakebin, state):
    run(home, fakebin, state, "install", "--agent", "codex")
    code, out = run(home, fakebin, state, "codex-confiar", "--sim")
    assert code != 0
    assert "terminal" in out and requests(state) == []


def test_codex_confiar_sim_is_refused_in_an_agent_session(home, fakebin, state):
    run(home, fakebin, state, "install", "--agent", "codex")
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim", extra={"CODEX_THREAD_ID": "t"})
    assert code != 0
    assert "CODEX_THREAD_ID" in out and requests(state) == []


def test_codex_confiar_is_in_the_help(home, fakebin, state):
    code, out = run(home, fakebin, state, "--help")
    assert "codex-confiar" in out


def test_a_lookalike_hook_is_not_trusted(home, fakebin, state):
    """Something that only looks like an Okeanos command (another clone, an injected path) is not ours."""
    run(home, fakebin, state, "install", "--agent", "codex")
    hooks_file = home / ".codex" / "hooks.json"
    data = json.loads(hooks_file.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": '"/tmp/evil/hooks/run" --agent codex stop'}]})
    hooks_file.write_text(json.dumps(data))
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim")
    assert code == 0, out
    trusted = writes(state)[0]["edits"][0]["value"]
    assert f"{hooks_file}:stop:1:0" not in trusted and len(trusted) == 6


# ---------------------------------------------------------------------------
# --project, and Orca
# ---------------------------------------------------------------------------

def test_project_trust_uses_the_repository_hooks(home, fakebin, state, project):
    hooks_file = project / ".codex" / "hooks.json"
    third = with_third_party(hooks_file)
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", "--project", answer="s", cwd=project)
    assert code == 0, out
    lists = [r for r in requests(state) if r.get("method") == "hooks/list"]
    assert lists and all(r["params"]["cwds"] == [str(project)] for r in lists)
    [write] = writes(state)
    assert set(write["edits"][0]["value"]) == okeanos_keys(hooks_file)
    assert third not in hooks_state(state)


def test_project_trust_under_orca_warns_it_may_need_rerunning(home, fakebin, state, project):
    codex = home / ".codex"
    codex.mkdir()
    (codex / ".orca-managed-home").write_text("")
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", "--project", answer="s", cwd=project)
    assert code == 0, out
    assert len(writes(state)) == 1
    assert "Orca" in out and "okeanos codex-confiar --project" in out


def test_user_level_trust_is_not_offered_under_orca(home, fakebin, state):
    codex = home / ".codex"
    codex.mkdir()
    (codex / ".orca-managed-home").write_text("")
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "[s/N]" not in out and requests(state) == []


# ---------------------------------------------------------------------------
# uninstall drops only the Okeanos hooks.state entries
# ---------------------------------------------------------------------------

def test_uninstall_removes_only_okeanos_trust_entries(home, fakebin, state):
    hooks_file = home / ".codex" / "hooks.json"
    third = with_third_party(hooks_file)
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    ours = okeanos_keys(hooks_file)
    elsewhere = "/somewhere/else/hooks.json:stop:0:0"
    current = hooks_state(state)
    current.update({third: {"trusted_hash": "sha256:3p"}, elsewhere: {"trusted_hash": "sha256:x"}})
    (state / "hooks_state.json").write_text(json.dumps(current))
    assert ours <= set(hooks_state(state))

    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--uninstall")
    assert code == 0, out
    last = writes(state)[-1]
    assert last["edits"][0]["mergeStrategy"] == "replace"
    assert last["expectedVersion"]
    assert hooks_state(state) == {third: {"trusted_hash": "sha256:3p"}, elsewhere: {"trusted_hash": "sha256:x"}}
    assert json.loads(hooks_file.read_text())["hooks"] == {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": THIRD_PARTY}]}]}


def test_project_uninstall_removes_only_okeanos_trust_entries(home, fakebin, state, project):
    hooks_file = project / ".codex" / "hooks.json"
    run_tty(home, fakebin, state, "install", "--agent", "codex", "--project", answer="s", cwd=project)
    assert okeanos_keys(hooks_file) <= set(hooks_state(state))
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--project", "--uninstall", cwd=project)
    assert code == 0, out
    assert hooks_state(state) == {}
    assert writes(state)[-1]["edits"][0]["mergeStrategy"] == "replace"


def test_uninstall_still_works_when_codex_fails(home, fakebin, state):
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    (state / "fail_start").write_text("")
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--uninstall")
    assert code == 0, out
    assert not (home / ".codex" / "hooks.json").exists() or not okeanos_keys(home / ".codex" / "hooks.json")
    assert "hooks.state" in out
