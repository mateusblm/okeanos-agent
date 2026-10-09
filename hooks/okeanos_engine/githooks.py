"""Per-project git hooks: `okeanos githooks [--uninstall]` and the checks they run.

The installed hooks are small sh scripts that call the user CLI (bin/okeanos, by the
absolute path resolved at install time) as `okeanos githook <name>`. They are the net
that works for any agent and for humans: pre-commit blocks secrets and weakened
committed tests (unless approved with `okeanos aprovar`), and warns about new lint/type
suppressions; pre-push runs the `onDone` commands from docs/agents/checks.json.

A hook already in place is kept as `<name>.okeanos-prev` and runs first. Missing
python3, a missing engine or an internal error never block: the hook passes with a
warning. `git commit --no-verify` skips them; that is the human's call (agents are
denied --no-verify by the agent hooks).
"""

import os
import shlex
import sys

from . import approvals
from .plumbing import git, load_checks, repo_root, run, tail
from .rules import (SUPPRESSION, added_lines, is_doc, is_env_file, is_test, secret_types,
                    weakened_test_lines)

HOOKS = ("pre-commit", "pre-push")
MARKER = "# okeanos-githook"
PREV_SUFFIX = ".okeanos-prev"
BLOCKED = 3  # exit code the sh wrapper turns into a failing hook; anything else unexpected passes

SCRIPT = """#!/bin/sh
{marker}: installed by `okeanos githooks`; `okeanos githooks --uninstall` removes it.
# Runs the hook that was here before (if any), then the Okeanos checks.
# Without python3 or the engine it warns and lets git go on.
OKEANOS_CLI={cli}
hook={name}
prev="${{0%/*}}/$hook{suffix}"
if [ -x "$prev" ]; then
  "$prev" "$@" || exit $?
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "[Okeanos] python3 não encontrado; hook $hook do Okeanos pulado." >&2
  exit 0
fi
if [ ! -f "$OKEANOS_CLI" ]; then
  echo "[Okeanos] motor não encontrado em $OKEANOS_CLI; hook $hook do Okeanos pulado. Rode \\`okeanos githooks\\` de novo." >&2
  exit 0
fi
python3 "$OKEANOS_CLI" githook "$hook" "$@" </dev/null
code=$?
[ "$code" -eq 0 ] && exit 0
[ "$code" -eq {blocked} ] && exit 1
echo "[Okeanos] o hook $hook do Okeanos falhou internamente (código $code); seguindo sem ele." >&2
exit 0
"""


def say(text):
    print(text, file=sys.stderr)


def script(name, cli):
    return SCRIPT.format(marker=MARKER, cli=shlex.quote(cli), name=name, suffix=PREV_SUFFIX, blocked=BLOCKED)


def hooks_dir(root):
    """The directory git runs hooks from: core.hooksPath or <git-common-dir>/hooks."""
    d = git(root, "rev-parse", "--git-path", "hooks")
    if not d:
        return None
    return os.path.normpath(d if os.path.isabs(d) else os.path.join(root, d))


def is_ours(path):
    try:
        with open(path, errors="ignore") as f:
            return MARKER in f.read(4096)
    except OSError:
        return False


def write_executable(path, content):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o755)


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------

def install(root, cli):
    d = hooks_dir(root)
    if not d:
        say("okeanos githooks: não achei a pasta de hooks deste repositório.")
        return 1
    os.makedirs(d, exist_ok=True)
    status = 0
    for name in HOOKS:
        path, prev = os.path.join(d, name), os.path.join(d, name + PREV_SUFFIX)
        content = script(name, cli)
        if os.path.lexists(path) and not is_ours(path):
            if os.path.lexists(prev):
                say(f"okeanos githooks: {path} não é do Okeanos e {prev} já existe; {name} não instalado. "
                    "Junte os dois à mão e rode de novo.")
                status = 1
                continue
            os.rename(path, prev)
            write_executable(path, content)
            print(f"{name}: instalado em {path}; o hook anterior virou {name}{PREV_SUFFIX} e roda antes.")
            continue
        try:
            with open(path) as f:
                current = f.read()
        except OSError:
            current = None
        if current == content and os.access(path, os.X_OK):
            print(f"{name}: já instalado em {path}.")
            continue
        write_executable(path, content)
        print(f"{name}: instalado em {path}.")
    return status


def uninstall(root):
    d = hooks_dir(root)
    if not d:
        say("okeanos githooks: não achei a pasta de hooks deste repositório.")
        return 1
    for name in HOOKS:
        path, prev = os.path.join(d, name), os.path.join(d, name + PREV_SUFFIX)
        if not is_ours(path):
            print(f"{name}: sem hook do Okeanos; nada a remover.")
            continue
        os.remove(path)
        if os.path.lexists(prev):
            os.rename(prev, path)
            print(f"{name}: removido; o hook anterior voltou para {path}.")
        else:
            print(f"{name}: removido.")
    return 0


# ---------------------------------------------------------------------------
# pre-commit
# ---------------------------------------------------------------------------

def staged_secrets(root, diff):
    findings = [f"{rel}: {name}" for rel, line in added_lines(diff) for name in secret_types(line)]
    for rel in (git(root, "diff", "--cached", "--name-only", "--diff-filter=A", "--no-renames") or "").splitlines():
        if is_env_file(rel):
            findings.append(f"{rel}: arquivo .env")
    return sorted(set(findings))


def weakened_tests(root):
    """{rel: [lines]} for committed tests whose staged version removes, alters or skips tests."""
    if git(root, "rev-parse", "--verify", "-q", "HEAD") is None:
        return {}
    checks = load_checks(root)
    out = {}
    for rel in (git(root, "diff", "--cached", "--name-only", "--no-renames") or "").splitlines():
        if not is_test(rel, checks) or git(root, "cat-file", "-e", f"HEAD:{rel}") is None:
            continue
        old = git(root, "show", f"HEAD:{rel}", timeout=20) or ""
        new = git(root, "show", f":{rel}", timeout=20) or ""  # None when the file is deleted
        lines = weakened_test_lines(old, new)
        if lines:
            out[rel] = lines
    return out


def pre_commit(root):
    diff = git(root, "-c", "core.quotePath=false", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff",
               "--no-renames", timeout=30) or ""
    secrets = staged_secrets(root, diff)
    if secrets:
        say("[Okeanos] pre-commit: possível segredo no commit:\n- " + "\n- ".join(secrets[:10])
            + "\nTire o segredo do código (variável de ambiente, .gitignore) e tire do stage antes de commitar.")
        return BLOCKED
    live = approvals.active(root)
    weakened = {rel: lines for rel, lines in weakened_tests(root).items() if rel not in live}
    if weakened:
        detail = "\n".join(f"{rel}:\n" + "\n".join(f"  - {l[:100]}" for l in lines[:5])
                           for rel, lines in sorted(weakened.items()))
        say("[Okeanos] pre-commit: este commit altera, remove ou desliga asserções ou casos de teste "
            f"já commitados:\n{detail}\nTestes commitados são o contrato: mudar exige aprovação. "
            "Adicionar testes não pede.\n" + approvals.how_to(sorted(weakened)))
        return BLOCKED
    suppressions = [f"{rel}: {line.strip()[:80]}" for rel, line in added_lines(diff)
                    if not is_doc(rel) and SUPPRESSION.search(line)]
    if suppressions:
        say("[Okeanos] pre-commit, aviso: supressão de lint/tipo nova:\n- " + "\n- ".join(suppressions[:10])
            + "\nConfira se cada uma tem motivo forte.")
    return 0


# ---------------------------------------------------------------------------
# pre-push
# ---------------------------------------------------------------------------

def pre_push(root):
    if not os.path.exists(os.path.join(root, "docs", "agents", "checks.json")):
        say("[Okeanos] pre-push: sem docs/agents/checks.json, nada a rodar (a skill onboard cria o arquivo).")
        return 0
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    failures = []
    for check in load_checks(root).get("onDone", []):
        cmd = check.get("cmd", "")
        if not cmd:
            continue
        code, out = run(cmd, root, timeout=int(check.get("timeout", 600)), shell=True, env=env)
        if code != 0:
            failures.append(f"[{check.get('name', 'check')}] `{cmd}` falhou:\n{tail(out)}")
    if failures:
        say("[Okeanos] pre-push: a definição de pronto falhou; push barrado.\n\n" + "\n\n".join(failures))
        return BLOCKED
    return 0


def run_hook(name):
    """Entry point of `okeanos githook <name>`. Internal errors pass with a warning."""
    try:
        root = repo_root(os.getcwd())
        if not root:
            return 0
        if name == "pre-commit":
            return pre_commit(root)
        if name == "pre-push":
            return pre_push(root)
        return 0
    except Exception as e:  # noqa: BLE001
        say(f"okeanos: erro interno no hook {name} ({e}); seguindo sem ele.")
        return 0
