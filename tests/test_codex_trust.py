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
def folder_trusted(cwd):
    return load("projects.json", {}).get(os.path.realpath(cwd), {}).get("trust_level") == "trusted"
def parse_key_path(p):  # codex-rs app-server/src/config_manager_service.rs parse_key_path
    segs, seg, quoted, it = [], "", False, iter(p)
    for ch in it:
        if ch == '"' and not seg and not quoted: quoted = True
        elif ch == '"' and quoted: quoted = False
        elif ch == "\\" and quoted: seg += next(it)
        elif ch == "." and not quoted: segs.append(seg); seg = ""
        elif ch == '"': raise ValueError("invalid quoted keyPath segment")
        else: seg += ch
    if quoted: raise ValueError("unterminated quoted keyPath segment")
    return segs + [seg]
def entries(cwd):
    files = [(os.path.join(codex_home, "hooks.json"), "user")]
    if folder_trusted(cwd):  # Codex loads the project layer (.codex/) only for trusted folders
        files.append((os.path.join(cwd, ".codex", "hooks.json"), "project"))
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
    bad = load("malformed.json", {}).get(method)  # method -> "no_hash" or a literal (malformed) result
    if bad == "no_hash":
        hs = [{k: v for k, v in h.items() if k != "currentHash"} for c in params["cwds"] for h in entries(c)]
        reply(i, {"data": [{"cwd": params["cwds"][0], "hooks": hs}]}); continue
    if bad is not None:
        reply(i, bad); continue
    if method == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "some/notification", "params": {}}) + "\n")
        reply(i, {"userAgent": "fake", "codexHome": codex_home})
    elif method == "hooks/list":
        reply(i, {"data": [{"cwd": c, "hooks": entries(c), "warnings": [], "errors": []} for c in params["cwds"]]})
    elif method == "config/read":
        state = load("hooks_state.json", {})
        reply(i, {"config": {}, "origins": {}, "layers": [
            {"name": {"type": "user", "file": os.path.join(codex_home, "config.toml"), "profile": None},
             "version": "v%d" % load("version.json", 0),
             "config": {"model": "x", "hooks": {"state": state}, "projects": load("projects.json", {})}}]})
    elif method == "config/batchWrite":
        if os.path.exists(path("fail_write")):
            reply(i, error="Invalid configuration: hooks.state is read-only here (fake)"); continue
        version = load("version.json", 0)
        if params.get("expectedVersion") not in (None, "v%d" % version):
            reply(i, error="configVersionConflict"); continue
        state, projects = load("hooks_state.json", {}), load("projects.json", {})
        for edit in params["edits"]:
            segs = parse_key_path(edit["keyPath"])
            if segs == ["hooks", "state"]:
                if edit["mergeStrategy"] == "replace": state = dict(edit["value"])
                else: state.update(edit["value"])
            else:
                assert len(segs) == 3 and segs[0] == "projects" and segs[2] == "trust_level", segs
                projects.setdefault(segs[1], {})["trust_level"] = edit["value"]
        save("hooks_state.json", state); save("projects.json", projects); save("version.json", version + 1)
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


def run_tty_answers(home, fakebin, state, *args, answers=(), cwd=None, extra=None):
    """Like run_tty, typing answers[i] at the i-th [s/N] question."""
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, str(CLI), *args], cwd=cwd or home, env=env_for(home, fakebin, state, extra),
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    chunks, answered = [], 0
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
        asked = b"".join(chunks).count(b"[s/N]")
        while answered < min(asked, len(answers)):
            os.write(master, (answers[answered] + "\n").encode())
            answered += 1
    os.close(master)
    return p.wait(timeout=60), b"".join(chunks).decode(errors="replace")


def trust_folder(state, folder):
    """The folder was trusted in Codex before (as the TUI's "Trust this folder" leaves it)."""
    (state / "projects.json").write_text(json.dumps({os.path.realpath(folder): {"trust_level": "trusted"}}))


def projects(state):
    path = state / "projects.json"
    return json.loads(path.read_text()) if path.exists() else {}


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
    trust_folder(state, project)
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
    trust_folder(state, project)
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
    trust_folder(state, project)
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


def test_each_hook_is_reported_once_even_if_codex_lists_its_file_twice(home, fakebin, state):
    """With cwd = HOME (trusted) the fake lists ~/.codex/hooks.json as user and as project layer, like an overlap could."""
    trust_folder(state, home)
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert out.count("confiado: Stop") == 1
    [write] = writes(state)
    assert len(write["edits"][0]["value"]) == 6


# ---------------------------------------------------------------------------
# --project in a folder Codex doesn't trust yet: a second, separate question
# ---------------------------------------------------------------------------

FOLDER_QUESTION = "Marcar a pasta como confiável no Codex?"


def folder_edit(folder):
    key = os.path.realpath(folder).replace("\\", "\\\\").replace('"', '\\"')
    return {"keyPath": f'projects."{key}".trust_level', "value": "trusted", "mergeStrategy": "replace"}


def test_untrusted_folder_yes_yes_trusts_the_folder_then_the_hooks(home, fakebin, state, project):
    hooks_file = project / ".codex" / "hooks.json"
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=project)
    assert code == 0, out
    assert "O Codex só carrega hooks de projetos confiáveis" in out
    assert f"esta pasta ({os.path.realpath(project)}) ainda não é" in out
    assert "resto da configuração em .codex/" in out
    folder, hooks = writes(state)
    assert folder["edits"] == [folder_edit(project)] and folder["reloadUserConfig"] is True
    assert set(hooks["edits"][0]["value"]) == okeanos_keys(hooks_file)
    assert projects(state) == {os.path.realpath(project): {"trust_level": "trusted"}}
    assert okeanos_keys(hooks_file) <= set(hooks_state(state))
    methods = [r.get("method") for r in requests(state)]
    assert methods.index("config/read") < methods.index("config/batchWrite")
    assert methods[-1] == "hooks/list"  # verified with Codex after the writes
    assert "NÃO" not in out


def test_untrusted_folder_declined_writes_nothing_and_says_how(home, fakebin, state, project):
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "n"], cwd=project)
    assert code == 0, out
    assert FOLDER_QUESTION in out
    assert writes(state) == [] and projects(state) == {} and hooks_state(state) == {}
    assert "Trust this folder" in out and "okeanos codex-confiar --project" in out


def test_folder_question_defaults_to_no(home, fakebin, state, project):
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", ""], cwd=project)
    assert code == 0, out
    assert FOLDER_QUESTION in out and writes(state) == []


def test_trusted_folder_gets_no_folder_question(home, fakebin, state, project):
    trust_folder(state, project)
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=project)
    assert code == 0, out
    assert FOLDER_QUESTION not in out and out.count("[s/N]") == 1
    [write] = writes(state)
    assert write["edits"][0]["keyPath"] == "hooks.state"


def test_codex_confiar_project_sim_trusts_folder_and_hooks(home, fakebin, state, project):
    run(home, fakebin, state, "install", "--agent", "codex", "--project", cwd=project)
    assert requests(state) == []
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--project", "--sim", answer="s", cwd=project)
    assert code == 0, out
    assert FOLDER_QUESTION in out and out.count("[s/N]") == 1  # --sim answers only the hooks question
    folder, hooks = writes(state)
    assert folder["edits"] == [folder_edit(project)]
    assert set(hooks["edits"][0]["value"]) == okeanos_keys(project / ".codex" / "hooks.json")


def test_codex_confiar_project_sim_without_a_terminal_writes_nothing(home, fakebin, state, project):
    run(home, fakebin, state, "install", "--agent", "codex", "--project", cwd=project)
    code, out = run(home, fakebin, state, "codex-confiar", "--project", "--sim", cwd=project)
    assert code != 0 and requests(state) == [] and projects(state) == {}


def test_install_project_in_an_agent_session_trusts_no_folder(home, fakebin, state, project):
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=project, extra={"CODEX_THREAD_ID": "t"})
    assert code == 0, out
    assert "[s/N]" not in out and requests(state) == [] and projects(state) == {}


def test_folder_key_escapes_a_quote_in_the_path(home, fakebin, state, tmp_path):
    weird = tmp_path / 'my "repo'
    weird.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=weird, check=True)
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=weird)
    assert code == 0, out
    folder, _ = writes(state)
    assert folder["edits"][0]["keyPath"] == 'projects."' + os.path.realpath(weird).replace('"', '\\"') + '".trust_level'
    assert projects(state) == {os.path.realpath(weird): {"trust_level": "trusted"}}
    assert okeanos_keys(weird / ".codex" / "hooks.json") <= set(hooks_state(state))


def test_linked_worktree_folder_is_not_trusted(home, fakebin, state, project):
    """Codex keys a linked worktree's trust by the main checkout, not this project's root: refuse."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=project, check=True)
    wt = project.parent / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt)], cwd=project, check=True)
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=wt)
    assert code == 0, out
    assert FOLDER_QUESTION not in out
    assert writes(state) == [] and projects(state) == {}
    assert os.path.realpath(project) in out


def test_project_uninstall_keeps_folder_trust(home, fakebin, state, project):
    trust_folder(state, project)
    run_tty(home, fakebin, state, "install", "--agent", "codex", "--project", answer="s", cwd=project)
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--project", "--uninstall", cwd=project)
    assert code == 0, out
    assert projects(state) == {os.path.realpath(project): {"trust_level": "trusted"}}
    assert "confiável" in out and "continua" in out


# ---------------------------------------------------------------------------
# uninstall forgets trust only when the Codex hooks were really removed
# ---------------------------------------------------------------------------

def test_failed_uninstall_keeps_the_okeanos_trust_entries(home, fakebin, state):
    """`--agent codex,foo` exits 2 without touching anything: the trust entries stay with the hooks."""
    hooks_file = home / ".codex" / "hooks.json"
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    before = hooks_state(state)
    assert okeanos_keys(hooks_file) <= set(before)
    code, out = run(home, fakebin, state, "install", "--agent", "codex,foo", "--uninstall")
    assert code == 2, out
    assert okeanos_keys(hooks_file) and hooks_state(state) == before
    assert len(writes(state)) == 1


def test_uninstall_aborted_for_codex_keeps_the_okeanos_trust_entries(home, fakebin, state):
    """The Codex plan aborts (config.toml isn't valid TOML): its hooks stay, and so does their trust."""
    hooks_file = home / ".codex" / "hooks.json"
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    before = hooks_state(state)
    (home / ".codex" / "config.toml").write_text("this is [not toml\n")
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--uninstall")
    assert code != 0, out
    assert okeanos_keys(hooks_file) and hooks_state(state) == before
    assert len(writes(state)) == 1


def test_uninstall_without_agent_removes_the_okeanos_trust_entries(home, fakebin, state):
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert hooks_state(state)
    code, out = run(home, fakebin, state, "install", "--uninstall")
    assert code == 0, out
    assert hooks_state(state) == {}


def test_install_without_agent_offers_codex_trust_when_codex_is_found(home, fakebin, state):
    code, out = run_tty(home, fakebin, state, "install", answer="s")
    assert code == 0, out
    assert okeanos_keys(home / ".codex" / "hooks.json") <= set(hooks_state(state))


def test_dry_run_neither_asks_nor_talks_to_codex(home, fakebin, state):
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", "--dry-run", answer="s")
    assert code == 0, out
    assert "[s/N]" not in out and requests(state) == []


# ---------------------------------------------------------------------------
# unexpected Codex responses fall back to /hooks without breaking the install
# ---------------------------------------------------------------------------

def malformed(state, method, result):
    (state / "malformed.json").write_text(json.dumps({method: result}))


@pytest.mark.parametrize("result", ["no_hash", [], {"data": "x"}, {"data": [{"hooks": 5}]}, "just a string"],
                         ids=["missing-currentHash", "result-list", "data-not-list", "hooks-not-list", "result-str"])
def test_malformed_hooks_list_falls_back_and_install_succeeds(home, fakebin, state, result):
    malformed(state, "hooks/list", result)
    code, out = run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    assert code == 0, out
    assert "Traceback" not in out
    assert "/hooks" in out and "não consegui confiar" in out
    assert hooks_state(state) == {}


def test_malformed_response_in_codex_confiar_falls_back(home, fakebin, state):
    run(home, fakebin, state, "install", "--agent", "codex")
    malformed(state, "hooks/list", [])
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--sim")
    assert code == 1, out
    assert "Traceback" not in out and "/hooks" in out


@pytest.mark.parametrize("result", [[], {"layers": 5}, {"config": "x", "layers": [{"name": "user"}]}],
                         ids=["result-list", "layers-not-list", "config-not-dict"])
def test_malformed_config_read_for_the_folder_falls_back(home, fakebin, state, project, result):
    malformed(state, "config/read", result)
    code, out = run_tty_answers(home, fakebin, state, "install", "--agent", "codex", "--project",
                                answers=["s", "s"], cwd=project)
    assert code == 0, out
    assert "Traceback" not in out and "/hooks" in out
    assert projects(state) == {}


@pytest.mark.parametrize("result", [[], {"layers": [{"name": {"type": "user"}, "config": "x"}]},
                                    {"layers": [{"name": {"type": "user"}, "config": {"hooks": {"state": 5}}}]}],
                         ids=["result-list", "config-not-dict", "state-not-dict"])
def test_malformed_config_read_on_uninstall_only_warns(home, fakebin, state, result):
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    malformed(state, "config/read", result)
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--uninstall")
    assert code == 0, out
    assert "Traceback" not in out and "hooks.state" in out
    assert not okeanos_keys(home / ".codex" / "hooks.json") if (home / ".codex" / "hooks.json").exists() else True


@pytest.mark.parametrize("result", [[], {"data": 5}, {"data": [{"hooks": [{"key": 5, "command": None}]}]}],
                         ids=["result-list", "data-not-list", "key-not-str"])
def test_malformed_hooks_list_on_uninstall_only_warns(home, fakebin, state, result):
    run_tty(home, fakebin, state, "install", "--agent", "codex", answer="s")
    malformed(state, "hooks/list", result)
    code, out = run(home, fakebin, state, "install", "--agent", "codex", "--uninstall")
    assert code == 0, out
    assert "Traceback" not in out
    assert not (home / ".codex" / "hooks.json").exists() or not okeanos_keys(home / ".codex" / "hooks.json")


# ---------------------------------------------------------------------------
# --sim answers only the hooks question: trusting the folder is always asked
# ---------------------------------------------------------------------------

def test_codex_confiar_project_sim_with_no_to_the_folder_writes_nothing(home, fakebin, state, project):
    run(home, fakebin, state, "install", "--agent", "codex", "--project", cwd=project)
    code, out = run_tty(home, fakebin, state, "codex-confiar", "--project", "--sim", answer="n", cwd=project)
    assert code == 0, out
    assert FOLDER_QUESTION in out and out.count("[s/N]") == 1
    assert writes(state) == [] and projects(state) == {} and hooks_state(state) == {}
