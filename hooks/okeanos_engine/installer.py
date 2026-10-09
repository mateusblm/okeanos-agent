"""`okeanos install`: put Okeanos into every coding agent found on this machine.

Each agent gets a plan (a list of actions) built from what is on disk; nothing is
written until every file the plan touches has parsed. A file that doesn't parse
aborts that agent only, with the file named. The plan is then applied (or just
printed, with --dry-run). Only Okeanos-owned pieces are ever changed or removed:
the marked block in AGENTS.md, hook handlers whose command runs this engine with
`--agent <agent>`, and symlinks into this repository. Every file is copied to
<file>.okeanos-bak before it changes.

Paths: OKEANOS_HOME_DIR replaces the home directory (tests), also as HOME for the
agent CLIs the installer runs. Codex's directory is $CODEX_HOME or ~/.codex, Copilot's
is $COPILOT_HOME or ~/.copilot (both variables are ignored when OKEANOS_HOME_DIR is set).
Codex, Copilot and Cursor share the skill links in ~/.agents/skills: uninstalling one agent
keeps them while another still has Okeanos.
Codex hooks go to hooks.json, or, when another tool manages that file (Orca rewrites it and drops our
entries) or with --codex-hooks toml, to [hooks] tables in config.toml between `# okeanos:start` and
`# okeanos:end`, appended at the end; the rest of config.toml is never rewritten.
Claude Code is installed through its own marketplace commands; its settings are
never touched. Cursor gets hooks in ~/.cursor/hooks.json; it has no file for global
rules, so `--project` writes the process as a project rule (.cursor/rules/okeanos.mdc)
in the current repository.
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

SUPPORTED = ("claude", "codex", "copilot", "cursor")
LATER = ()
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


def copilot_dir(home):
    if not os.environ.get("OKEANOS_HOME_DIR") and os.environ.get("COPILOT_HOME"):
        return os.environ["COPILOT_HOME"]
    return os.path.join(home, ".copilot")


def shared_skills_dir(home):
    return os.path.join(home, ".agents", "skills")


def skill_dirs(root):
    """{name: absolute folder} from the plugin manifest, the one list of shipped skills."""
    with open(os.path.join(root, ".claude-plugin", "plugin.json")) as f:
        paths = json.load(f)["skills"]
    return {os.path.basename(p.rstrip("/")): os.path.normpath(os.path.join(root, p)) for p in paths}


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

class Write:
    def __init__(self, path, content, what, keep_backup=True):
        self.path, self.content, self.what, self.keep_backup = path, content, what, keep_backup

    def describe(self):
        return f"{self.what}: {self.path}"

    def apply(self):
        if self.keep_backup:
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
    def __init__(self, path, what, keep_backup=True):
        self.path, self.what, self.keep_backup = path, what, keep_backup

    def describe(self):
        return f"{self.what}: {self.path}"

    def apply(self):
        if not os.path.islink(self.path) and self.keep_backup:
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


def block_actions(root, md_path, uninstall):
    """The process block between the okeanos markers in an instructions file."""
    md = read(md_path)
    if uninstall:
        if md is None or BLOCK_START not in md:
            return []
        rest = without_block(md)
        return [Write(md_path, rest, "remove bloco do processo") if rest
                else Remove(md_path, f"remove {os.path.basename(md_path)} (só tinha o bloco do Okeanos)")]
    with open(os.path.join(root, "adapters", "agents-md", "okeanos.md")) as f:
        block = f.read()
    new_md = with_block(md or "", block)
    return [Write(md_path, new_md, "bloco do processo")] if new_md != md else []


def shared_skill_actions(agent, root, home, uninstall, notes):
    """The ~/.agents/skills links, read by Codex, Copilot and Cursor alike: on uninstall they stay while
    another of those agents still has Okeanos."""
    if uninstall:
        others = [a for a, installed in SKILL_USERS.items() if a != agent and installed(root, home)]
        if others:
            notes.append(f"skills em {shared_skills_dir(home)} mantidas: ainda usadas pelo {', '.join(others)}.")
            return []
    return skill_actions(root, shared_skills_dir(home), uninstall, notes)


TOML_START = "# okeanos:start"
TOML_END = "# okeanos:end"
TOML_BLOCK_RE = re.compile(r"(?m)^" + re.escape(TOML_START) + r"[^\n]*\n(.*?)^" + re.escape(TOML_END) + r"[^\n]*(?:\n|\Z)", re.S)
TOML_HEADER_RE = re.compile(r"(?m)^[ \t]*\[")
ORCA_MARK = ".orca/agent-hooks"


def toml_string(value):
    out = []
    for ch in value:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def codex_hooks_toml(root):
    """The Okeanos hooks as config.toml tables, between the marker comments."""
    lines = [TOML_START, "# escrito por okeanos install; okeanos install --uninstall remove este bloco"]
    for event, groups in codex_hooks(root).items():
        for g in groups:
            lines += ["", f"[[hooks.{event}]]"]
            if "matcher" in g:
                lines.append(f"matcher = {toml_string(g['matcher'])}")
            for h in g["hooks"]:
                lines += ["", f"[[hooks.{event}.hooks]]"]
                lines += [f"type = {toml_string(h['type'])}", f"command = {toml_string(h['command'])}",
                          f"timeout = {int(h['timeout'])}"]
                if "statusMessage" in h:
                    lines.append(f"statusMessage = {toml_string(h['statusMessage'])}")
    return "\n".join(lines) + "\n" + TOML_END + "\n"


def foreign_tables(inside):
    """Tables Codex itself put inside the Okeanos block (its [hooks.state."..."] trust records): kept on rewrite."""
    starts = [m.start() for m in TOML_HEADER_RE.finditer(inside)] + [len(inside)]
    kept = []
    for a, b in zip(starts, starts[1:]):
        section = inside[a:b]
        if section.lstrip().startswith("[hooks.state"):
            kept.append(section.rstrip("\n") + "\n")
    return "".join(kept)


def toml_without_block(text):
    """config.toml without the Okeanos block (and the blank line put before it), keeping Codex's trust records."""
    m = TOML_BLOCK_RE.search(text)
    if not m:
        return text
    before, after, kept = text[:m.start()], text[m.end():], foreign_tables(m.group(1))
    if before.endswith("\n\n"):
        before = before[:-1]
    if kept:
        before = (before + "\n" if before and not before.endswith("\n\n") else before) + kept
    return before + after


def toml_with_block(text, block):
    rest = toml_without_block(text)
    if rest and not rest.endswith("\n"):
        rest += "\n"
    return rest + ("\n" if rest else "") + block


def parse_toml(path, text, what):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Abort(f"{path}: {what} ({e}). Nada foi alterado.")


def codex_toml_actions(root, path, uninstall):
    """The Okeanos [hooks] tables appended to config.toml between marker comments; the rest of the file is kept
    byte for byte. The result must parse before anything is written."""
    text = read(path) or ""
    new = toml_without_block(text) if uninstall else toml_with_block(text, codex_hooks_toml(root))
    if new == text:
        return []
    if tomllib is None:
        raise Abort(f"escrever hooks em {path} precisa do Python 3.11+ (tomllib). Nada foi alterado.")
    config = parse_toml(path, new, "ficaria TOML inválido com o bloco do Okeanos: o arquivo já define [hooks] "
                        "de um jeito que não aceita [[hooks.<evento>]] no fim (ex.: listas inline em [hooks]); "
                        "passe esses hooks para o formato [[hooks.<evento>]] ou use --codex-hooks json")
    if not uninstall and not toml_okeanos_installed(config):
        raise Abort(f"{path}: os hooks do Okeanos não ficariam legíveis depois do bloco (confira as tabelas [hooks]). "
                    "Nada foi alterado.")
    if uninstall and not new.strip():
        return [Remove(path, "remove config.toml (só tinha o bloco do Okeanos)")]
    return [Write(path, new, "remove hooks (config.toml)" if uninstall else "hooks (config.toml)")]


def toml_okeanos_installed(config):
    hooks = config.get("hooks") if isinstance(config, dict) else None
    owned = owned_command("codex")
    return isinstance(hooks, dict) and any(
        isinstance(groups, list) and any(
            isinstance(g, dict) and isinstance(g.get("hooks"), list) and any(
                isinstance(h, dict) and owned.search(str(h.get("command", ""))) for h in g["hooks"])
            for g in groups)
        for groups in hooks.values())


def codex_toml_has_block(cdir):
    return bool(TOML_BLOCK_RE.search(read(os.path.join(cdir, "config.toml")) or ""))


def managed_by_orca(data):
    return any(isinstance(h, dict) and ORCA_MARK in str(h.get("command", ""))
               for groups in data.get("hooks", {}).values() for g in groups for h in g.get("hooks", []))


def plan_codex(root, home, uninstall, hooks_mode=None):
    """hooks_mode: "json" (hooks.json), "toml" ([hooks] tables in config.toml) or None to pick: toml when another
    tool (Orca) manages hooks.json, since it rewrites that file and drops our entries."""
    notes, actions = [], []
    cdir = codex_dir(home)
    toml_path = os.path.join(cdir, "config.toml")
    check_codex_toml(toml_path, notes)

    hooks_path = os.path.join(cdir, "hooks.json")
    current = load_hooks_json(hooks_path)
    orca = managed_by_orca(current)
    mode = hooks_mode or ("toml" if orca else "json")
    new = strip_owned(current, "codex")
    if not uninstall and mode == "json":
        new.setdefault("hooks", {})
        for event, groups in codex_hooks(root).items():
            new["hooks"].setdefault(event, []).extend(groups)
    if new != current and (current or not uninstall):
        actions.append(Write(hooks_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                             "hooks" if mode == "json" and not uninstall else "remove hooks"))
    actions += codex_toml_actions(root, toml_path, uninstall or mode == "json")

    actions += block_actions(root, os.path.join(cdir, "AGENTS.md"), uninstall)
    if not uninstall:
        override = read(os.path.join(cdir, "AGENTS.override.md"))
        if override and override.strip():
            notes.append(f"aviso: {os.path.join(cdir, 'AGENTS.override.md')} existe e o Codex lê ele no lugar do "
                         "AGENTS.md global; o processo do Okeanos não será carregado enquanto ele existir.")

    actions += shared_skill_actions("codex", root, home, uninstall, notes)
    if not uninstall and mode == "toml":
        why = (f"o {hooks_path} é gerenciado pelo Orca (hooks em {ORCA_MARK}), que reescreve o arquivo"
               if orca and not hooks_mode else "--codex-hooks toml")
        notes.append(f"hooks em {toml_path} ([hooks]), não no hooks.json: {why}. "
                     "O Codex junta os hooks dos dois arquivos (e avisa disso ao iniciar).")
    hooks_written = any(isinstance(a, Write) and a.path in (hooks_path, toml_path) and not a.what.startswith("remove")
                        for a in actions)
    if not uninstall and hooks_written:
        notes.append("próximo passo: abra o Codex e rode /hooks para revisar e confiar nos hooks do Okeanos; "
                     "o Codex não roda hooks novos ou alterados antes disso.")
    return actions, notes


def codex_installed(root, home):
    cdir = codex_dir(home)
    try:
        hooks = load_hooks_json(os.path.join(cdir, "hooks.json"))
    except Abort:
        return True  # can't tell: keep what it may use
    md = read(os.path.join(cdir, "AGENTS.md")) or ""
    return BLOCK_START in md or strip_owned(hooks, "codex") != hooks or codex_toml_has_block(cdir)


# ---------------------------------------------------------------------------
# Copilot (CLI): user hooks file, user instructions, shared skills
# ---------------------------------------------------------------------------

COPILOT_HOOKS_FILE = "okeanos.json"
COPILOT_EDIT_TOOLS = "edit|create|write|str_replace_editor|apply_patch"


def copilot_hooks(root):
    """camelCase events (the CLI's native `version: 1` format), one entry per handler."""
    run = f'"{root}/hooks/run" --agent copilot'
    onboard = f'"{root}/hooks/onboard-check.sh" --agent copilot'

    def h(command, timeout, matcher=None):
        out = {"type": "command", "bash": command, "timeoutSec": timeout}
        if matcher:
            out["matcher"] = matcher
        return out

    return {
        "sessionStart": [h(onboard, 10), h(f"{run} session-start", 10)],
        "preToolUse": [h(f"{run} pre-tool", 30, "bash|powershell|" + COPILOT_EDIT_TOOLS)],
        "postToolUse": [h(f"{run} post-tool", 120, COPILOT_EDIT_TOOLS)],
        "agentStop": [h(f"{run} stop", 1800)],
    }


def load_copilot_hooks(path):
    """The parsed hooks file ({} when missing). Abort unless it is Copilot's `version: 1` shape."""
    text = read(path)
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Abort(f"{path} não é JSON válido ({e}). Nada foi alterado; corrija o arquivo e rode de novo.")
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    ok = (isinstance(hooks, dict) and data.get("version", 1) == 1
          and all(isinstance(entries, list) and all(isinstance(e, dict) for e in entries) for entries in hooks.values()))
    if not ok:
        raise Abort(f"{path} não tem o formato de hooks do Copilot ({{\"version\": 1, \"hooks\": {{<evento>: [...]}}}}). "
                    "Nada foi alterado; corrija o arquivo e rode de novo.")
    return data


def strip_owned_flat(data, agent):
    """A copy of a Copilot hooks config without this agent's Okeanos entries (and the events they emptied)."""
    data = json.loads(json.dumps(data))
    owned = owned_command(agent)
    hooks = data.get("hooks", {})
    for event in list(hooks):
        kept = [e for e in hooks[event] if not owned.search(str(e.get("bash", "")) + " " + str(e.get("command", "")))]
        if kept or not hooks[event]:
            hooks[event] = kept
        else:
            del hooks[event]
    return data


def copilot_installed(root, home):
    cdir = copilot_dir(home)
    try:
        hooks = load_copilot_hooks(os.path.join(cdir, "hooks", COPILOT_HOOKS_FILE))
    except Abort:
        return True
    md = read(os.path.join(cdir, "copilot-instructions.md")) or ""
    return BLOCK_START in md or strip_owned_flat(hooks, "copilot") != hooks


def check_copilot_settings(path, notes):
    """Never written; only read for disableAllHooks."""
    text = read(path)
    if not text:
        return
    try:
        settings = json.loads(text)
    except ValueError:
        notes.append(f"aviso: não consegui ler {path}; confira se ele não tem disableAllHooks: true.")
        return
    if isinstance(settings, dict) and settings.get("disableAllHooks") is True:
        notes.append(f"aviso: {path} tem disableAllHooks: true; as proteções do Okeanos não vão rodar no Copilot.")


def plan_copilot(root, home, uninstall):
    notes, actions = [], []
    cdir = copilot_dir(home)
    check_copilot_settings(os.path.join(cdir, "settings.json"), notes)

    hooks_path = os.path.join(cdir, "hooks", COPILOT_HOOKS_FILE)
    current = load_copilot_hooks(hooks_path)
    new = strip_owned_flat(current, "copilot")
    if uninstall:
        if current and new != current:
            leftover = {k: v for k, v in new.items() if k not in ("version", "hooks")} or any(new.get("hooks", {}).values())
            actions.append(Write(hooks_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n", "remove hooks")
                           if leftover else Remove(hooks_path, "remove hooks"))
    else:
        new.setdefault("version", 1)
        new.setdefault("hooks", {})
        for event, entries in copilot_hooks(root).items():
            new["hooks"].setdefault(event, []).extend(entries)
        if new != current:
            actions.append(Write(hooks_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n", "hooks"))

    actions += block_actions(root, os.path.join(cdir, "copilot-instructions.md"), uninstall)
    actions += shared_skill_actions("copilot", root, home, uninstall, notes)
    if not uninstall and actions:
        notes.append("próximo passo: reinicie o Copilot CLI (hooks e instruções são lidos quando ele inicia). "
                     "Os hooks de usuário não valem no Copilot na nuvem, que só lê .github/hooks do repositório.")
    return actions, notes


# ---------------------------------------------------------------------------
# Cursor (https://cursor.com/docs/agent/hooks): flat hooks.json, version 1
# ---------------------------------------------------------------------------

CURSOR_FILE_TOOLS = "Write|StrReplace|Delete|Edit|MultiEdit"
CURSOR_RULE = os.path.join(".cursor", "rules", "okeanos.mdc")
CURSOR_RULE_FRONTMATTER = ("---\ndescription: Processo Okeanos (rotas, gates e definição de pronto). "
                           "Gerado por `okeanos install --agent cursor --project`.\nalwaysApply: true\n---\n\n")


def cursor_dir(home):
    return os.path.join(home, ".cursor")


def cursor_found(home):
    return shutil.which("cursor") or shutil.which("cursor-agent") or (
        os.path.isdir(cursor_dir(home)) and cursor_dir(home))


def cursor_hooks(root):
    run = f'"{root}/hooks/run" --agent cursor'
    onboard = f'"{root}/hooks/onboard-check.sh" --agent cursor'
    return {
        "sessionStart": [{"command": onboard, "timeout": 10}, {"command": f"{run} session-start", "timeout": 10}],
        "beforeShellExecution": [{"command": f"{run} shell", "timeout": 30}],
        "preToolUse": [{"command": f"{run} pre-tool", "matcher": CURSOR_FILE_TOOLS, "timeout": 30}],
        "postToolUse": [{"command": f"{run} post-tool", "matcher": CURSOR_FILE_TOOLS, "timeout": 120}],
        "afterAgentResponse": [{"command": f"{run} agent-response", "timeout": 10}],
        "stop": [{"command": f"{run} stop", "timeout": 1800}],
    }


def load_cursor_hooks(path):
    """The parsed ~/.cursor/hooks.json ({} when missing). Abort if it isn't the documented shape."""
    text = read(path)
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Abort(f"{path} não é JSON válido ({e}). Nada foi alterado; corrija o arquivo e rode de novo.")
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    ok = isinstance(hooks, dict) and all(
        isinstance(entries, list) and all(isinstance(h, dict) for h in entries) for entries in hooks.values())
    if not ok:
        raise Abort(f"{path} não tem o formato de hooks do Cursor ({{\"version\": 1, \"hooks\": {{<evento>: [...]}}}}). "
                    "Nada foi alterado; corrija o arquivo e rode de novo.")
    return data


def cursor_installed(root, home):
    try:
        hooks = load_cursor_hooks(os.path.join(cursor_dir(home), "hooks.json"))
    except Abort:
        return True  # can't tell: keep what it may use
    return strip_owned_flat(hooks, "cursor") != hooks


def plan_cursor(root, home, uninstall):
    notes, actions = [], []
    hooks_path = os.path.join(cursor_dir(home), "hooks.json")
    current = load_cursor_hooks(hooks_path)
    new = strip_owned_flat(current, "cursor")
    if not uninstall:
        new.setdefault("version", 1)
        new.setdefault("hooks", {})
        for event, entries in cursor_hooks(root).items():
            new["hooks"].setdefault(event, []).extend(entries)
    if new != current and (current or not uninstall):
        actions.append(Write(hooks_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                             "remove hooks" if uninstall else "hooks"))
    actions += shared_skill_actions("cursor", root, home, uninstall, notes)
    if not uninstall:
        notes.append("regras: o Cursor guarda as regras globais (User Rules) só na interface, sem arquivo. Para o "
                     "processo do Okeanos valer, rode `okeanos install --agent cursor --project` na raiz de cada "
                     "repositório (escreve .cursor/rules/okeanos.mdc) ou cole o conteúdo de "
                     f"{os.path.join(root, 'adapters', 'agents-md', 'okeanos.md')} em Customize → Rules.")
        if any(isinstance(a, Write) and a.path == hooks_path for a in actions):
            notes.append("próximo passo: confira em Cursor Settings → Hooks que os hooks do Okeanos aparecem; "
                         "se não aparecerem, reinicie o Cursor.")
    return actions, notes


def plan_cursor_project(root, repo, uninstall):
    """The process as an always-applied Cursor project rule in repo."""
    path = os.path.join(repo, CURSOR_RULE)
    current = read(path)
    if current is not None and BLOCK_START not in current:
        raise Abort(f"{path} já existe e não é do Okeanos. Nada foi alterado.")
    if uninstall:
        return ([Remove(path, "remove regra do projeto", keep_backup=False)] if current is not None else []), []
    with open(os.path.join(root, "adapters", "agents-md", "okeanos.md")) as f:
        wanted = CURSOR_RULE_FRONTMATTER + f.read()
    actions = [] if current == wanted else [Write(path, wanted, "regra do projeto", keep_backup=False)]
    notes = [f"commite {CURSOR_RULE} para valer para quem usa o Cursor neste repositório (ou ponha no .gitignore); "
             "depois de atualizar o Okeanos, rode este comando de novo."]
    return actions, notes


SKILL_USERS = {"codex": codex_installed, "copilot": copilot_installed, "cursor": cursor_installed}


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


PLANNERS = {"claude": plan_claude, "codex": plan_codex, "copilot": plan_copilot, "cursor": plan_cursor}
FILE_AGENTS = ("codex", "copilot", "cursor")  # installed by writing files: uninstall looks for them even off the PATH


def status(root=None, home=None):
    """{agent: [installed pieces]} for the agents installed by writing files (for `okeanos doctor`)."""
    root, home = root or plugin_root(), home or home_dir()
    skills = os.path.join(shared_skills_dir(home), "")
    linked = os.path.isdir(skills) and any(
        os.path.islink(os.path.join(skills, n)) and os.readlink(os.path.join(skills, n)).startswith(os.path.join(root, "skills"))
        for n in os.listdir(skills))
    out = {}
    for agent, hooks_path, load, strip, md_path in (
            ("codex", os.path.join(codex_dir(home), "hooks.json"), load_hooks_json, strip_owned,
             os.path.join(codex_dir(home), "AGENTS.md")),
            ("copilot", os.path.join(copilot_dir(home), "hooks", COPILOT_HOOKS_FILE), load_copilot_hooks,
             strip_owned_flat, os.path.join(copilot_dir(home), "copilot-instructions.md")),
            ("cursor", os.path.join(cursor_dir(home), "hooks.json"), load_cursor_hooks, strip_owned_flat, None)):
        pieces = []
        try:
            data = load(hooks_path)
            if strip(data, agent) != data:
                pieces.append("hooks")
        except Abort:
            pieces.append("hooks ilegíveis")
        if agent == "codex" and codex_toml_has_block(codex_dir(home)):
            pieces.append("hooks em config.toml")
        if md_path and BLOCK_START in (read(md_path) or ""):
            pieces.append("instruções")
        if pieces and linked:
            pieces.append("skills")
        out[agent] = pieces
    return out


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


def found(agent, home):
    """Where this agent was found on this machine, or None."""
    return cursor_found(home) if agent == "cursor" else shutil.which(agent)


def run_project(names, root, uninstall, dry_run, out):
    """`okeanos install --agent cursor --project`: the process rule in the current repository."""
    if names != ["cursor"]:
        out("okeanos install: --project só vale para o Cursor: okeanos install --agent cursor --project")
        return 2
    from .plumbing import repo_root
    repo = repo_root(os.getcwd())
    if not repo:
        out("okeanos install --project: aqui não é um repositório git; rode na raiz do projeto.")
        return 2
    prefix = "(simulação) " if dry_run else ""
    out(f"{prefix}Okeanos {'desinstalação' if uninstall else 'instalação'} no projeto {repo}")
    try:
        actions, notes = plan_cursor_project(root, repo, uninstall)
    except Abort as e:
        out(f"cursor (projeto): ERRO, nada instalado: {e}")
        return 1
    return 0 if report("cursor (projeto)", actions, notes, dry_run, prefix, out) else 1


def run(agents_arg, uninstall=False, dry_run=False, out=print, project=False, codex_hooks=None):
    root, home = plugin_root(), home_dir()
    names, bad = requested_agents(agents_arg)
    if bad:
        later = [n for n in bad if n in LATER]
        out("okeanos install: " + ", ".join(f"`{n}` ainda não é suportado" if n in later else f"agente desconhecido `{n}`"
                                            for n in bad) + f". Suportados: {', '.join(SUPPORTED)}.")
        return 2
    if project:
        return run_project(names, root, uninstall, dry_run, out)
    prefix = "(simulação) " if dry_run else ""
    out(f"{prefix}Okeanos {'desinstalação' if uninstall else 'instalação'} a partir de {root}")
    if not names:
        found_at = {a: found(a, home) for a in SUPPORTED}
        names = [a for a in SUPPORTED if found_at[a] or (uninstall and a in FILE_AGENTS)]
        for a in SUPPORTED:
            if not found_at[a] and not (uninstall and a in FILE_AGENTS):
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
            extra = {"hooks_mode": codex_hooks} if agent == "codex" else {}
            actions, notes = PLANNERS[agent](root, home, uninstall, **extra)
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
