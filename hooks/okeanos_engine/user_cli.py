"""The user's command line: `okeanos <subcommand>` (entry script: bin/okeanos).

Unlike the hooks, this is run by the human. `aprovar` and `revogar` change what the
agent may do, so they refuse unless stdin and stdout are a terminal (an agent's shell
has neither) and refuse inside an agent session, recognised by the variables the agents
set in their tool shells. The rules also deny any agent command that runs them.
"""

import argparse
import os
import shutil
import sys
import time

from . import approvals, githooks, installer
from .cli import metrics_summary
from .plumbing import git, repo_root

AGENT_CLIS = ("claude", "codex", "copilot", "cursor-agent")
# Set by the agents in the shell where they run tools (Codex 0.161: CODEX_THREAD_ID, CODEX_SESSION_ID,
# CODEX_CI, plus CODEX_SANDBOX* when sandboxed; Claude Code: CLAUDECODE).
AGENT_SESSION_VARS = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI", "CODEX_SANDBOX",
                      "CODEX_SANDBOX_NETWORK_DISABLED")
IN_AGENT = ("okeanos {sub}: recusado, `{var}` mostra que este shell é de uma sessão de agente. "
            "Aprovações são do humano: rode `okeanos {sub} ...` num terminal seu, fora do agente.")
TTY_ONLY = ("okeanos {sub}: recusado, este comando precisa de um terminal interativo. "
            "Aprovações são do humano: rode `okeanos {sub} ...` no seu próprio terminal, não pelo agente.")


def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def interactive():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:  # noqa: BLE001
        return False


def human_only(sub):
    """None if a human may run `sub` here; else the refusal message."""
    for var in AGENT_SESSION_VARS:
        if os.environ.get(var):
            return IN_AGENT.format(sub=sub, var=var)
    if not interactive():
        return TTY_ONLY.format(sub=sub)
    return None


def clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def current_repo():
    root = repo_root(os.getcwd())
    if not root:
        print("okeanos: aqui não é um repositório git.", file=sys.stderr)
    return root


def normalize_target(root, raw):
    """(target, error). push, pacote:<nome>, or a file committed at HEAD (repo-relative)."""
    if raw == approvals.PUSH:
        return raw, None
    if raw.startswith(approvals.PACKAGE_PREFIX):
        name = raw[len(approvals.PACKAGE_PREFIX):].strip()
        if not name or any(ch.isspace() for ch in name):
            return None, f"`{raw}`: diga o nome do pacote, como `pacote:expresss`."
        return approvals.PACKAGE_PREFIX + name, None
    full = os.path.normpath(os.path.join(os.getcwd(), os.path.expanduser(raw)))
    real_root = os.path.realpath(root)
    full = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
    if not full.startswith(real_root + os.sep):
        return None, f"`{raw}` fica fora do repositório."
    rel = os.path.relpath(full, real_root)
    if git(root, "cat-file", "-e", f"HEAD:{rel}") is None:
        return None, (f"`{raw}` não é um arquivo commitado. Alvos aprováveis: um teste commitado, "
                      "`push` ou `pacote:<nome>`. Segredos, force push, --no-verify, rm -r fora do repo "
                      "e pacote inexistente nunca são aprováveis.")
    return rel, None


def cmd_aprovar(args):
    refusal = human_only("aprovar")
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    root = current_repo()
    if not root:
        return 1
    targets = []
    for raw in args.alvos:
        target, error = normalize_target(root, raw)
        if error:
            print("okeanos aprovar: " + error, file=sys.stderr)
            return 1
        targets.append(target)
    expires = approvals.grant(root, targets)
    for t in targets:
        print(f"Aprovado: {t} até {clock(expires)} (10 minutos).")
    return 0


def cmd_aprovacoes(args):
    root = current_repo()
    if not root:
        return 1
    live = approvals.active(root)
    if not live:
        print("Nenhuma aprovação ativa.")
        return 0
    for target, expires in sorted(live.items()):
        print(f"{target}  até {clock(expires)}")
    return 0


def cmd_revogar(args):
    refusal = human_only("revogar")
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    root = current_repo()
    if not root:
        return 1
    removed = approvals.revoke(root, args.alvo)
    if not removed:
        print("Nada a revogar." if args.alvo is None else f"Sem aprovação para {args.alvo}.")
    for t in removed:
        print(f"Revogado: {t}")
    return 0


def cmd_metrics(args):
    metrics_summary(args.dias, by_agent=True, now=approvals.now())
    return 0


def cmd_githooks(args):
    root = current_repo()
    if not root:
        return 1
    if args.uninstall:
        return githooks.uninstall(root)
    cli = os.path.join(os.path.realpath(plugin_root()), "bin", "okeanos")
    return githooks.install(root, cli)


def cmd_githook(args):
    """Called by the installed git hooks, not by people."""
    return githooks.run_hook(args.hook)


def cmd_install(args):
    return installer.run(args.agent, uninstall=args.uninstall, dry_run=args.dry_run)


def cmd_doctor(args):
    yes = lambda ok: "sim" if ok else "não"  # noqa: E731
    print(f"plugin: {plugin_root()}")
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    root = repo_root(os.getcwd())
    print(f"repositório: {root or 'não (fora de um repositório git)'}")
    if root:
        print(f"  CLAUDE.md: {yes(os.path.exists(os.path.join(root, 'CLAUDE.md')) or os.path.exists(os.path.join(root, '.claude', 'CLAUDE.md')))}")
        print(f"  AGENTS.md: {yes(os.path.exists(os.path.join(root, 'AGENTS.md')))}")
        print(f"  docs/agents/checks.json: {yes(os.path.exists(os.path.join(root, 'docs', 'agents', 'checks.json')))}")
        live = approvals.active(root)
        print("aprovações ativas: " + (", ".join(f"{t} até {clock(e)}" for t, e in sorted(live.items())) or "nenhuma"))
    print("agentes no PATH:")
    for name in AGENT_CLIS:
        found = shutil.which(name)
        print(f"  {name}: {found or 'não encontrado'}")
    return 0


def parser():
    p = argparse.ArgumentParser(prog="okeanos", description="Okeanos: aprovações, métricas e diagnóstico.")
    sub = p.add_subparsers(dest="sub", metavar="<comando>")
    a = sub.add_parser("aprovar", help="libera um alvo por 10 minutos (só num terminal interativo)",
                       description="Alvos: um teste commitado (caminho no repo), `push` (git push, PR, merge na "
                                   "branch padrão) ou `pacote:<nome>`. Segredos e bloqueios duros nunca são aprováveis.")
    a.add_argument("alvos", nargs="+", metavar="alvo")
    a.set_defaults(func=cmd_aprovar)
    sub.add_parser("aprovacoes", help="lista as aprovações ativas").set_defaults(func=cmd_aprovacoes)
    r = sub.add_parser("revogar", help="remove uma aprovação (ou todas, sem alvo)")
    r.add_argument("alvo", nargs="?")
    r.set_defaults(func=cmd_revogar)
    m = sub.add_parser("metrics", help="eventos dos hooks por tipo e por agente")
    m.add_argument("dias", nargs="?", type=int, default=30)
    m.set_defaults(func=cmd_metrics)
    g = sub.add_parser("githooks", help="instala os git hooks do Okeanos (pre-commit, pre-push) neste repositório",
                       description="pre-commit: barra segredos e testes commitados afrouxados sem `okeanos aprovar`, "
                                   "avisa de supressões novas. pre-push: roda os comandos onDone de "
                                   "docs/agents/checks.json. Hooks que já existiam são mantidos e rodam antes.")
    g.add_argument("--uninstall", action="store_true", help="remove os hooks do Okeanos e devolve os anteriores")
    g.set_defaults(func=cmd_githooks)
    h = sub.add_parser("githook")  # no help: internal, run by the installed hooks
    h.add_argument("hook", choices=githooks.HOOKS)
    h.add_argument("rest", nargs=argparse.REMAINDER)
    h.set_defaults(func=cmd_githook)
    i = sub.add_parser("install", help="instala o Okeanos nos agentes encontrados (Claude Code, Codex)",
                       description="Detecta os agentes no PATH e instala em cada um: Claude Code pelo marketplace; "
                                   "Codex com skills em ~/.agents/skills, o bloco do processo no AGENTS.md global e os "
                                   "hooks no hooks.json do usuário. Também liga a CLI em ~/.local/bin. Idempotente; "
                                   "edita só o que é do Okeanos e guarda <arquivo>.okeanos-bak antes de mudar.")
    i.add_argument("--agent", action="append", metavar="AGENTE",
                   help="só este agente (repita ou separe por vírgula): claude, codex")
    i.add_argument("--uninstall", action="store_true", help="remove só o que o Okeanos instalou")
    i.add_argument("--dry-run", action="store_true", help="mostra o que faria, sem mudar nada")
    i.set_defaults(func=cmd_install)
    sub.add_parser("doctor", help="mostra onde o Okeanos está e o que encontra aqui").set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)
