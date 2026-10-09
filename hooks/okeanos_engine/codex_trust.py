"""Trust for the Okeanos hooks in Codex, asked of the human and recorded by Codex itself.

Codex runs a non-managed hook only after the user trusts its exact definition (hooks.state in the user's
config.toml, keyed by `<hooks file>:<event>:<group>:<handler>` with the hash Codex computed). We never compute
that hash: `codex app-server` (stdio JSON-RPC, the same calls the TUI's /hooks makes) lists the hooks with their
key, currentHash and trustStatus, and `config/batchWrite` records the trust. Only Okeanos entries are touched:
the command is exactly one the installer writes for this clone (`installer.codex_hooks`) and the key starts with
the hooks file we installed into. A failure never breaks the install: it says why and points to /hooks.
"""

import json
import os
import select
import shutil
import subprocess
import tempfile
import time

from . import installer
from .plumbing import git_common_dir, repo_root

TIMEOUT = 20
NEEDS_REVIEW = ("untrusted", "modified")


class TrustError(Exception):
    """Codex could not list or trust the hooks; the message carries Codex's reason."""


def unexpected(method, what):
    return TrustError(f"resposta inesperada do Codex a {method}: {what}")


# ---------------------------------------------------------------------------
# where: the hooks files Okeanos writes, and the cwd Codex resolves them from
# ---------------------------------------------------------------------------

class Scope:
    def __init__(self, files, cwd, project):
        self.files, self.cwd, self.project = files, cwd, project

    def where(self):
        return f" neste projeto ({self.cwd})" if self.project else ""

    def later(self):
        return "okeanos codex-confiar" + (" --project" if self.project else "")


def user_scope(home):
    cdir = installer.codex_dir(home)
    return Scope([os.path.join(cdir, "hooks.json"), os.path.join(cdir, "config.toml")], home, False)


def project_scope(repo):
    return Scope([os.path.join(repo, installer.CODEX_PROJECT_HOOKS)], repo, True)


def installed(scope, home):
    """Okeanos hooks are in this scope's files (and Codex will read them)."""
    if scope.project:
        return installer.codex_project_installed(scope.cwd)
    return not installer.orca_managed(home) and installer.codex_user_hooks(home)


def okeanos_commands(root):
    return {h["command"] for groups in installer.codex_hooks(root).values() for g in groups for h in g["hooks"]}


def is_ours(hook, scope, commands):
    prefixes = {p + ":" for f in scope.files for p in (f, os.path.realpath(f))}
    key = str(hook.get("key", ""))
    return hook.get("command") in commands and any(key.startswith(p) for p in prefixes)


# ---------------------------------------------------------------------------
# codex app-server over stdio
# ---------------------------------------------------------------------------

def plugin_version(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json")) as f:
            return str(json.load(f).get("version", "0"))
    except (OSError, ValueError):
        return "0"


class AppServer:
    """A `codex app-server` child speaking newline-delimited JSON-RPC, with the user's Codex home."""

    def __init__(self, cwd, home, root, timeout=TIMEOUT):
        env = installer.agent_env()
        env["CODEX_HOME"] = installer.codex_dir(home)
        codex = shutil.which("codex", path=env.get("PATH"))
        if not codex:
            raise TrustError("o comando `codex` não está no PATH")
        self.timeout, self.next_id, self.buffer = timeout, 0, b""
        self.stderr = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=self.stderr, cwd=cwd, env=env)
        except OSError as e:
            raise TrustError(f"não consegui iniciar `codex app-server` ({e})")
        try:
            self.request("initialize", {"clientInfo": {"name": "okeanos", "title": "Okeanos",
                                                       "version": plugin_version(root)}})
            self.send({"jsonrpc": "2.0", "method": "initialized"})
        except TrustError:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.stderr.close()

    def died(self):
        self.stderr.seek(0)
        tail = self.stderr.read().decode(errors="replace").strip()[-400:]
        return TrustError("`codex app-server` encerrou" + (f": {tail}" if tail else " sem resposta"))

    def send(self, msg):
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
            self.proc.stdin.flush()
        except OSError:
            self.proc.poll()
            raise self.died()

    def read_message(self, deadline):
        while b"\n" not in self.buffer:
            left = deadline - time.monotonic()
            ready = select.select([self.proc.stdout], [], [], max(left, 0))[0] if left > 0 else []
            if not ready:
                return None
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                self.proc.wait(timeout=3)
                raise self.died()
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            return json.loads(line)
        except ValueError:
            return {}

    def request(self, method, params):
        self.next_id += 1
        rid = self.next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            msg = self.read_message(deadline)
            if msg is None:
                raise TrustError(f"`codex app-server` não respondeu a {method} em {self.timeout}s")
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == rid and "method" not in msg:
                if msg.get("error"):
                    err = msg["error"]
                    reason = err.get("message") if isinstance(err, dict) else str(err)
                    raise TrustError(f"{method} recusado pelo Codex: {reason}")
                result = msg.get("result")
                if result is None:
                    return {}
                if not isinstance(result, dict):
                    raise unexpected(method, "o resultado não é um objeto")
                return result
            if "id" in msg and "method" in msg:  # a request from the server: we don't serve any
                self.send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})


def list_ours(server, scope, commands):
    result = server.request("hooks/list", {"cwds": [scope.cwd]})
    data = result.get("data", [])
    if not isinstance(data, list) or not all(isinstance(e, dict) and isinstance(e.get("hooks", []), list)
                                             for e in data):
        raise unexpected("hooks/list", "`data` não é uma lista de {cwd, hooks: [...]}")
    hooks = [h for entry in data for h in entry.get("hooks", []) if isinstance(h, dict)]
    ours = {}
    for h in hooks:  # one entry per key: the same file can show up under more than one layer
        if is_ours(h, scope, commands):
            ours.setdefault(h["key"], h)
    return list(ours.values())


def event_label(hook):
    name = str(hook.get("eventName", "?"))
    return name[:1].upper() + name[1:]


# ---------------------------------------------------------------------------
# consent, trust, verify
# ---------------------------------------------------------------------------

def describe_hooks(root, scope, out):
    out("Hooks do Okeanos para o Codex" + (f" ({scope.files[0]})" if scope.project else "") + ":")
    for event, groups in installer.codex_hooks(root).items():
        for g in groups:
            for h in g["hooks"]:
                out(f"  {event} [{g.get('matcher', '*')}]: {h['command']}")
    out("Esses comandos rodam fora do sandbox do Codex, com as permissões do seu usuário.")


def later_note(scope):
    return (f"Para confiar depois, num terminal seu (fora do agente): {scope.later()}. Ou abra o Codex{scope.where()}: "
            "ao iniciar ele oferece \"Trust all and continue\" (ou rode /hooks).")


def fallback_note(scope, reason):
    return (f"codex: não consegui confiar nos hooks do Okeanos: {reason}. Faça pelo Codex: abra-o{scope.where()}, "
            "rode /hooks e confie nos hooks do Okeanos (ou escolha \"Trust all and continue\" quando ele pedir).")


def orca_note(scope, home):
    if scope.project and installer.orca_managed(home):
        return ("Orca: a confiança fica no config.toml do CODEX_HOME, que o Orca regenera; se o Codex voltar a pedir "
                f"revisão dos hooks, rode {scope.later()} de novo.")
    return None


# ---------------------------------------------------------------------------
# folder trust: Codex loads a project's .codex/ (hooks included) only for trusted folders
# ---------------------------------------------------------------------------

def folder_key(repo):
    """(key, None) or (None, why not). Codex keys folder trust by `project_trust_key` (the canonicalized path,
    codex-rs config/src/loader/mod.rs) of `resolve_root_git_project_for_trust` (codex-rs git-utils/src/trust.rs):
    the checkout whose .git is a directory, or, for a linked worktree, its main checkout. We only trust the
    current project's own repository root, so a linked worktree (trust would land on the main checkout) is refused."""
    real = os.path.realpath(repo)
    top = repo_root(repo)
    if not top or os.path.realpath(top) != real:
        return None, f"{repo} não é a raiz de um repositório git; não marco a pasta como confiável"
    if not os.path.isdir(os.path.join(real, ".git")):
        common = git_common_dir(real)
        main = os.path.realpath(os.path.dirname(common)) if common else "?"
        return None, (f"o Codex guarda a confiança deste worktree na pasta principal ({main}), que não é a raiz "
                      f"deste projeto ({real}); não marco essa pasta como confiável")
    return real, None


def folder_edit(key):
    """The TUI's own edit (codex-rs tui/src/config_update.rs, trusted_project_edit)."""
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return {"keyPath": f'projects."{escaped}".trust_level', "value": "trusted", "mergeStrategy": "replace"}


def read_config(server, scope):
    """config/read with layers: (effective config, user layers, base layer first). Shapes checked."""
    result = server.request("config/read", {"includeLayers": True, "cwd": scope.cwd})
    config, layers = result.get("config") or {}, result.get("layers") or []
    if not isinstance(config, dict) or not isinstance(layers, list):
        raise unexpected("config/read", "`config` não é um objeto ou `layers` não é uma lista")
    users = [l for l in layers if isinstance(l, dict) and isinstance(l.get("name"), dict)
             and l["name"].get("type") == "user"]
    if not all(isinstance(l.get("config") or {}, dict) for l in users):
        raise unexpected("config/read", "a camada do usuário não traz um objeto em `config`")
    users.sort(key=lambda l: l["name"].get("profile") is not None)
    return config, users


def folder_trusted(server, scope, key):
    """The effective config or the user layer has projects.<key>.trust_level = "trusted"."""
    config, users = read_config(server, scope)
    for config in [config] + [l.get("config") or {} for l in users]:
        projects = config.get("projects")
        entry = projects.get(key) if isinstance(projects, dict) else None
        if isinstance(entry, dict) and entry.get("trust_level") == "trusted":
            return True
    return False


def folder_question(key):
    return (f"O Codex só carrega hooks de projetos confiáveis, e esta pasta ({key}) ainda não é. Marcar a pasta "
            "como confiável no Codex? Isso também faz o Codex carregar o resto da configuração em .codex/ deste "
            "repositório. [s/N] ")


def folder_later_note(scope):
    return (f"Para fazer depois: abra o Codex nesta pasta ({scope.cwd}) e aceite \"Trust this folder\"; "
            f"depois rode {scope.later()}.")


def trust_folder(server, scope, commands, confirm, out):
    """No Okeanos project hooks listed: if the folder is untrusted, ask, trust it and list again.
    Returns the listed hooks, or None when the human declined."""
    missing = TrustError(f"o Codex não lista hooks do Okeanos em {', '.join(scope.files)}")
    key, why = folder_key(scope.cwd)
    if why:
        raise TrustError(why)
    if folder_trusted(server, scope, key):
        raise missing
    if not confirm(folder_question(key)):
        out("codex: nada foi confiado; a pasta continua não confiável no Codex.")
        out(folder_later_note(scope))
        return None
    server.request("config/batchWrite", {"edits": [folder_edit(key)], "reloadUserConfig": True})
    out(f"codex: pasta marcada como confiável no Codex: {key}")
    ours = list_ours(server, scope, commands)
    if not ours:
        raise missing
    return ours


def trust(scope, root, home, out, confirm):
    """Trust the Okeanos hooks that need review, then check with Codex. True when all of them are trusted,
    None when the human declined trusting the folder (--project in a folder Codex doesn't trust yet)."""
    commands = okeanos_commands(root)
    try:
        with AppServer(scope.cwd, home, root) as server:
            ours = list_ours(server, scope, commands)
            if not ours and scope.project:
                ours = trust_folder(server, scope, commands, confirm, out)
                if ours is None:
                    return None
            if not ours:
                raise TrustError(f"o Codex não lista hooks do Okeanos em {', '.join(scope.files)}")
            pending = [h for h in ours if h.get("trustStatus") in NEEDS_REVIEW]
            if not all(isinstance(h.get("currentHash"), str) and h["currentHash"] for h in pending):
                raise unexpected("hooks/list", "hook sem `currentHash`")
            if not pending:
                out("codex: os hooks do Okeanos já estão confiados.")
                return True
            server.request("config/batchWrite", {
                "edits": [{"keyPath": "hooks.state",
                           "value": {h["key"]: {"trusted_hash": h["currentHash"]} for h in pending},
                           "mergeStrategy": "upsert"}],
                "reloadUserConfig": True})
            after = {h.get("key"): h for h in list_ours(server, scope, commands)}
    except TrustError as e:
        out(fallback_note(scope, e))
        return False
    ok = True
    out("codex: confiança registrada pelo Codex:")
    for h in pending:
        status = (after.get(h["key"]) or {}).get("trustStatus", "ausente")
        good = status == "trusted"
        ok &= good
        out(f"  {'confiado' if good else 'NÃO ' + 'confiado (' + status + ')'}: {event_label(h)} "
            f"[{h.get('matcher') or '*'}] {h.get('command')}")
    if not ok:
        out(fallback_note(scope, "a verificação depois da escrita não confirmou todos"))
    return ok


def offer(scope, root, home, refusal, ask, out=print, ask_fn=input):
    """The consent step. refusal: why a human can't be asked here (no terminal, agent session), or None.
    Returns 0 when trusted or declined, 1 when refused or Codex failed."""
    if refusal:
        out(f"codex: hooks do Okeanos não confiados agora ({refusal}).")
        out(later_note(scope))
        return 1
    def confirm(question):
        try:
            answer = ask_fn(question)
        except EOFError:
            answer = ""
        return answer.strip().lower() in ("s", "sim", "y", "yes")

    describe_hooks(root, scope, out)
    # --sim (ask=False) answers yes to this question only: trusting the folder is always asked
    if ask and not confirm("Autorizar esses hooks no Codex agora? [s/N] "):
        out("codex: nada foi confiado.")
        out(later_note(scope))
        return 0
    try:
        ok = trust(scope, root, home, out, confirm)
    except Exception as e:  # noqa: BLE001 - never break the install: fall back to /hooks
        out(fallback_note(scope, f"erro inesperado ({type(e).__name__}: {e})"))
        ok = False
    if ok is None:
        return 0
    note = orca_note(scope, home)
    if note:
        out(note)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# uninstall: drop the Okeanos entries from hooks.state
# ---------------------------------------------------------------------------

def okeanos_keys(scope, root, home):
    """Keys of the Okeanos hooks as Codex sees them now (call before the hooks are removed)."""
    with AppServer(scope.cwd, home, root) as server:
        return {h["key"] for h in list_ours(server, scope, okeanos_commands(root)) if h.get("key")}


def forget(scope, keys, root, home):
    """Rewrite the user's hooks.state without `keys`. Returns how many entries were removed.
    config/batchWrite rejects null, so the remaining map goes back whole with mergeStrategy replace,
    guarded by the user layer's version."""
    with AppServer(scope.cwd, home, root) as server:
        _, layers = read_config(server, scope)
        if not layers:
            return 0
        hooks = (layers[0].get("config") or {}).get("hooks") or {}
        current = hooks.get("state") if isinstance(hooks, dict) else None
        if current is None:
            return 0
        if not isinstance(current, dict):
            raise unexpected("config/read", "`hooks.state` não é uma tabela")
        remaining = {k: v for k, v in current.items() if k not in keys}
        if len(remaining) == len(current):
            return 0
        params = {"edits": [{"keyPath": "hooks.state", "value": remaining, "mergeStrategy": "replace"}],
                  "reloadUserConfig": True}
        if layers[0].get("version"):
            params["expectedVersion"] = layers[0]["version"]
        server.request("config/batchWrite", params)
        return len(current) - len(remaining)
