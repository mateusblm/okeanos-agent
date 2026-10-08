"""`okeanos install`: put Okeanos into every coding agent found on this machine.

Each agent gets a plan (a list of actions) built from what is on disk; nothing is
written until every file the plan touches has parsed. A file that doesn't parse
aborts that agent only, with the file named. The plan is then applied (or just
printed, with --dry-run). Only Okeanos-owned pieces are ever changed or removed:
the marked block in AGENTS.md, hook handlers whose command runs this engine with
`--agent <agent>`, and symlinks into this repository. Every file is copied to
<file>.okeanos-bak before it changes.

Paths: OKEANOS_HOME_DIR replaces the home directory (tests), also as HOME for the
agent CLIs the installer runs. Codex's directory is
$CODEX_HOME or ~/.codex (CODEX_HOME is ignored when OKEANOS_HOME_DIR is set).
Claude Code is installed through its own marketplace commands; its settings are
never touched.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

try:
    import tomllib
except ImportError:  # Python < 3.11: config.toml can't be checked, and we never write it
    tomllib = None

SUPPORTED = ("claude", "codex")
LATER = ("copilot", "cursor")
BLOCK_START = "<!-- okeanos:start -->"
BLOCK_END = "<!-- okeanos:end -->"
BACKUP = ".okeanos-bak"
PLUGIN_ID = "okeanos@okeanos"


class Abort(Exception):
    """This agent can't be installed safely; the message says which file and why."""


# ---------------------------------------------------------------------------
# where things live
# ---------------------------------------------------------------------------

def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def home_dir():
    return os.environ.get("OKEANOS_HOME_DIR") or os.path.expanduser("~")


def agent_env():
    """Environment for agent CLIs: with OKEANOS_HOME_DIR set, they see that directory as HOME too,
    so a test or trial run never reaches the real ~/.claude."""
    env = dict(os.environ)
    if os.environ.get("OKEANOS_HOME_DIR"):
        env["HOME"] = os.environ["OKEANOS_HOME_DIR"]
        env.pop("CLAUDE_CONFIG_DIR", None)
    return env


def codex_dir(home):
    if not os.environ.get("OKEANOS_HOME_DIR") and os.environ.get("CODEX_HOME"):
        return os.environ["CODEX_HOME"]
    return os.path.join(home, ".codex")


def skill_dirs(root):
    """{name: absolute folder} from the plugin manifest, the one list of shipped skills."""
    with open(os.path.join(root, ".claude-plugin", "plugin.json")) as f:
        paths = json.load(f)["skills"]
    return {os.path.basename(p.rstrip("/")): os.path.normpath(os.path.join(root, p)) for p in paths}


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

class Write:
    def __init__(self, path, content, what):
        self.path, self.content, self.what = path, content, what

    def describe(self):
        return f"{self.what}: {self.path}"

    def apply(self):
        backup(self.path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".okeanos-")
        with os.fdopen(fd, "w") as f:
            f.write(self.content)
        if os.path.exists(self.path):
            shutil.copymode(self.path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)


class Link:
    def __init__(self, path, target, what):
        self.path, self.target, self.what = path, target, what

    def describe(self):
        return f"{self.what}: {self.path} -> {self.target}"

    def apply(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.islink(self.path):
            os.unlink(self.path)
        os.symlink(self.target, self.path)


class Remove:
    def __init__(self, path, what):
        self.path, self.what = path, what

    def describe(self):
        return f"{self.what}: {self.path}"

    def apply(self):
        if not os.path.islink(self.path):
            backup(self.path)
        os.unlink(self.path)


class Run:
    def __init__(self, argv, what):
        self.argv, self.what = argv, what

    def describe(self):
        return f"{self.what}: {' '.join(self.argv)}"

    def apply(self):
        p = subprocess.run(self.argv, capture_output=True, text=True, timeout=300, env=agent_env())
        if p.returncode != 0:
            raise RuntimeError(f"`{' '.join(self.argv)}` falhou: {(p.stdout + p.stderr).strip()[-500:]}")


def backup(path):
    if os.path.isfile(path) and not os.path.islink(path):
        shutil.copy2(path, path + BACKUP)


# ---------------------------------------------------------------------------
# marked block in an instructions file
# ---------------------------------------------------------------------------

BLOCK_RE = re.compile(r"\n*" + re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)


def without_block(text):
    stripped = BLOCK_RE.sub("\n", text).strip("\n")
    return stripped + "\n" if stripped else ""


def with_block(text, block):
    rest = without_block(text)
    return (rest + "\n" if rest else "") + block


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------

def owned_command(agent):
    return re.compile(r"hooks/(run|onboard-check\.sh)[\"']?\s+--agent[ =]" + re.escape(agent) + r"\b")


def codex_hooks(root):
    run = f'"{root}/hooks/run" --agent codex'
    onboard = f'"{root}/hooks/onboard-check.sh" --agent codex'

    def h(command, timeout, status=None):
        out = {"type": "command", "command": command, "timeout": timeout}
        if status:
            out["statusMessage"] = status
        return out

    return {
        "SessionStart": [{"matcher": "startup|resume", "hooks": [h(onboard, 10), h(f"{run} session-start", 10)]}],
        "UserPromptSubmit": [{"hooks": [h(f"{run} prompt", 10)]}],
        "PreToolUse": [{"matcher": "Bash|apply_patch", "hooks": [h(f"{run} pre-tool", 30)]}],
        "PostToolUse": [{"matcher": "apply_patch", "hooks": [h(f"{run} post-tool", 120, "Okeanos: format e lint")]}],
        "Stop": [{"hooks": [h(f"{run} stop", 1800, "Okeanos: definição de pronto")]}],
    }


def load_hooks_json(path):
    """The parsed hooks file ({} when missing). Abort if it isn't the documented shape."""
    text = read(path)
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Abort(f"{path} não é JSON válido ({e}). Nada foi alterado; corrija o arquivo e rode de novo.")
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    ok = isinstance(hooks, dict) and all(
        isinstance(groups, list) and all(isinstance(g, dict) and isinstance(g.get("hooks", []), list) for g in groups)
        for groups in hooks.values())
    if not ok:
        raise Abort(f"{path} não tem o formato de hooks do Codex ({{\"hooks\": {{<evento>: [...]}}}}). "
                    "Nada foi alterado; corrija o arquivo e rode de novo.")
    return data


def strip_owned(data, agent):
    """A copy of a hooks config without this agent's Okeanos handlers (and the groups/events they emptied)."""
    data = json.loads(json.dumps(data))
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    owned = owned_command(agent)
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            handlers = g.get("hooks", [])
            kept = [h for h in handlers if not (isinstance(h, dict) and owned.search(str(h.get("command", ""))))]
            if kept or len(kept) == len(handlers):
                groups.append({**g, "hooks": kept} if len(kept) != len(handlers) else g)
        if groups or not hooks[event]:
            hooks[event] = groups
        else:
            del hooks[event]
    return data


def check_codex_toml(path, notes):
    text = read(path)
    if text is None or tomllib is None:
        return
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Abort(f"{path} não é TOML válido ({e}). Nada foi alterado; corrija o arquivo e rode de novo.")
    features = config.get("features", {})
    if isinstance(features, dict) and (features.get("hooks") is False or features.get("codex_hooks") is False):
        notes.append(f"aviso: {path} desliga os hooks ([features] hooks = false); as proteções do Okeanos não vão rodar.")


def skill_actions(root, skills_dir, uninstall, notes):
    actions, ours = [], os.path.join(root, "skills") + os.sep
    wanted = {} if uninstall else skill_dirs(root)
    owned = lambda p: os.path.islink(p) and os.path.join(os.path.dirname(p), os.readlink(p)).startswith(ours)  # noqa: E731
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            path = os.path.join(skills_dir, name)
            if owned(path) and name not in wanted:
                actions.append(Remove(path, f"remove skill {name}"))
    for name, target in sorted(wanted.items()):
        path = os.path.join(skills_dir, name)
        if os.path.islink(path) and os.readlink(path) == target:
            continue
        if os.path.lexists(path) and not owned(path):
            notes.append(f"aviso: {path} já existe e não é do Okeanos; a skill `{name}` do Okeanos não foi instalada ali.")
            continue
        actions.append(Link(path, target, f"skill {name}"))
    return actions


def plan_codex(root, home, uninstall):
    notes, actions = [], []
    cdir = codex_dir(home)
    check_codex_toml(os.path.join(cdir, "config.toml"), notes)

    hooks_path = os.path.join(cdir, "hooks.json")
    current = load_hooks_json(hooks_path)
    new = strip_owned(current, "codex")
    if not uninstall:
        new.setdefault("hooks", {})
        for event, groups in codex_hooks(root).items():
            new["hooks"].setdefault(event, []).extend(groups)
    if new != current and (current or not uninstall):
        actions.append(Write(hooks_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                             "remove hooks" if uninstall else "hooks"))

    md_path = os.path.join(cdir, "AGENTS.md")
    md = read(md_path)
    if uninstall:
        if md is not None and BLOCK_START in md:
            rest = without_block(md)
            actions.append(Write(md_path, rest, "remove bloco do processo") if rest
                           else Remove(md_path, "remove AGENTS.md (só tinha o bloco do Okeanos)"))
    else:
        with open(os.path.join(root, "adapters", "agents-md", "okeanos.md")) as f:
            block = f.read()
        new_md = with_block(md or "", block)
        if new_md != md:
            actions.append(Write(md_path, new_md, "bloco do processo"))
        override = read(os.path.join(cdir, "AGENTS.override.md"))
        if override and override.strip():
            notes.append(f"aviso: {os.path.join(cdir, 'AGENTS.override.md')} existe e o Codex lê ele no lugar do "
                         "AGENTS.md global; o processo do Okeanos não será carregado enquanto ele existir.")

    actions += skill_actions(root, os.path.join(home, ".agents", "skills"), uninstall, notes)
    if not uninstall and any(isinstance(a, Write) and a.path == hooks_path for a in actions):
        notes.append("próximo passo: abra o Codex e rode /hooks para revisar e confiar nos hooks do Okeanos; "
                     "o Codex não roda hooks novos ou alterados antes disso.")
    return actions, notes


# ---------------------------------------------------------------------------
# Claude Code: the marketplace does the work
# ---------------------------------------------------------------------------

def claude_json(claude, *args):
    try:
        p = subprocess.run([claude, *args, "--json"], capture_output=True, text=True, timeout=120, env=agent_env())
        data = json.loads(p.stdout)
        if not isinstance(data, list):
            raise ValueError
        return data
    except Exception as e:  # noqa: BLE001
        raise Abort(f"`claude {' '.join(args)} --json` não respondeu como esperado ({e}); nada foi alterado.")


def plan_claude(root, home, uninstall):
    claude = shutil.which("claude")
    if not claude:
        raise Abort("o comando `claude` não está no PATH.")
    markets = {m.get("name") for m in claude_json(claude, "plugin", "marketplace", "list") if isinstance(m, dict)}
    plugins = {p.get("id") for p in claude_json(claude, "plugin", "list") if isinstance(p, dict)}
    actions, notes = [], []
    if uninstall:
        if PLUGIN_ID in plugins:
            actions.append(Run(["claude", "plugin", "uninstall", PLUGIN_ID], "remove plugin"))
        if "okeanos" in markets:
            actions.append(Run(["claude", "plugin", "marketplace", "remove", "okeanos"], "remove marketplace"))
        return actions, notes
    if "okeanos" not in markets:
        actions.append(Run(["claude", "plugin", "marketplace", "add", root], "marketplace"))
    if PLUGIN_ID not in plugins:
        actions.append(Run(["claude", "plugin", "install", PLUGIN_ID], "plugin"))
    else:
        notes.append(f"plugin {PLUGIN_ID} já instalado (para atualizar: claude plugin marketplace update okeanos "
                     f"&& claude plugin update {PLUGIN_ID}).")
    return actions, notes


PLANNERS = {"claude": plan_claude, "codex": plan_codex}


# ---------------------------------------------------------------------------
# the CLI on the user's PATH
# ---------------------------------------------------------------------------

def plan_cli(root, home, uninstall):
    bin_dir = os.path.join(home, ".local", "bin")
    path, target = os.path.join(bin_dir, "okeanos"), os.path.join(root, "bin", "okeanos")
    owned = os.path.islink(path) and os.readlink(path).endswith(os.path.join("bin", "okeanos"))
    actions, notes = [], []
    if uninstall:
        if owned:
            actions.append(Remove(path, "remove CLI"))
        return actions, notes
    if os.path.lexists(path) and not owned:
        notes.append(f"aviso: {path} já existe e não é do Okeanos; a CLI não foi ligada ali.")
    elif not (owned and os.readlink(path) == target):
        actions.append(Link(path, target, "CLI"))
    on_path = [os.path.normpath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if os.path.normpath(bin_dir) not in on_path:
        notes.append(f"aviso: {bin_dir} não está no PATH; adicione-o ao seu shell para usar `okeanos`.")
    return actions, notes


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def requested_agents(raw):
    names = [n.strip() for item in raw or [] for n in item.split(",") if n.strip()]
    bad = [n for n in names if n not in SUPPORTED]
    return names, bad


def run(agents_arg, uninstall=False, dry_run=False, out=print):
    root, home = plugin_root(), home_dir()
    names, bad = requested_agents(agents_arg)
    if bad:
        later = [n for n in bad if n in LATER]
        out("okeanos install: " + ", ".join(f"`{n}` ainda não é suportado" if n in later else f"agente desconhecido `{n}`"
                                            for n in bad) + f". Suportados: {', '.join(SUPPORTED)}.")
        return 2
    prefix = "(simulação) " if dry_run else ""
    out(f"{prefix}Okeanos {'desinstalação' if uninstall else 'instalação'} a partir de {root}")
    if not names:
        found = {a: shutil.which(a) for a in SUPPORTED}
        names = [a for a in SUPPORTED if found[a]] if not uninstall else [a for a in SUPPORTED if found[a] or a == "codex"]
        for a in SUPPORTED:
            if not found[a] and not (uninstall and a == "codex"):
                out(f"{a}: não encontrado no PATH")
        if not names:
            out("Nenhum agente suportado encontrado no PATH (" + ", ".join(SUPPORTED) + "). Nada foi alterado.")
            return 0
        with_cli = True
    else:
        with_cli = not uninstall

    failed, done = False, False
    for agent in names:
        try:
            actions, notes = PLANNERS[agent](root, home, uninstall)
        except Abort as e:
            out(f"{agent}: ERRO, nada instalado: {e}")
            failed = True
            continue
        failed |= not report(agent, actions, notes, dry_run, prefix, out)
        done = True
    if with_cli and (done or uninstall):
        actions, notes = plan_cli(root, home, uninstall)
        failed |= not report("cli", actions, notes, dry_run, prefix, out)
    return 1 if failed else 0


def summary(actions):
    """One line per action, except skills: one line per kind of change, with the names."""
    lines, skills = [], {}
    for a in actions:
        if a.what.startswith(("skill ", "remove skill ")):
            verb, name = a.what.rsplit(" ", 1)
            skills.setdefault((verb, os.path.dirname(a.path)), []).append(name)
        else:
            lines.append(a.describe())
    for (verb, where), names in skills.items():
        lines.append(f"{'remove skills' if verb.startswith('remove') else 'skills'} ({len(names)}) em {where}: "
                     + ", ".join(names))
    return lines


def report(name, actions, notes, dry_run, prefix, out):
    out(f"{name}:" + ("" if actions or notes else " nada a fazer, já está em dia"))
    for line in summary(actions):
        out(f"  {prefix}{line}")
    ok = True
    for a in actions:
        if dry_run:
            continue
        try:
            a.apply()
        except Exception as e:  # noqa: BLE001
            out(f"  ERRO: {e}")
            ok = False
            break
    for n in notes:
        out(f"  {n}")
    return ok
