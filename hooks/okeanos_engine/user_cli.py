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

from . import approvals, codex_trust, githooks, installer
from .cli import metrics_summary
from .plumbing import git, repo_root

AGENT_CLIS = ("claude", "codex", "copilot", "cursor", "cursor-agent")
# Set by the agents in the shell where they run tools (Codex 0.161: CODEX_THREAD_ID, CODEX_SESSION_ID,
# CODEX_CI, plus CODEX_SANDBOX* when sandboxed; Claude Code: CLAUDECODE; Cursor: CURSOR_AGENT, set by
# the IDE's agent terminals and cursor-agent, not in Cursor's official docs, so the TTY check still matters).
AGENT_SESSION_VARS = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI", "CODEX_SANDBOX",
                      "CODEX_SANDBOX_NETWORK_DISABLED", "CURSOR_AGENT")
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


def agent_session_var():
    return next((var for var in AGENT_SESSION_VARS if os.environ.get(var)), None)


def human_only(sub):
    """None if a human may run `sub` here; else the refusal message."""
    var = agent_session_var()
    if var:
        return IN_AGENT.format(sub=sub, var=var)
    if not interactive():
        return TTY_ONLY.format(sub=sub)
    return None


def consent_refusal():
    """Why the human can't be asked for consent here (short, for the install report), or None."""
    if human_only("install") is None:
        return None
    var = agent_session_var()
    return f"`{var}` mostra que este shell é de uma sessão de agente" if var else "sem terminal interativo"


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


def codex_scope(project):
    """The Codex hooks this install touches: the repository's (--project) or the user's; None outside a repo."""
    if not project:
        return codex_trust.user_scope(installer.home_dir())
    root = repo_root(os.getcwd())
    return codex_trust.project_scope(root) if root else None


def cmd_install(args):
    home, root = installer.home_dir(), installer.plugin_root()
    scope = None if args.dry_run else codex_scope(args.project)
    keys = None

    def before(agent):  # the trust keys must be read while the hooks are still there
        nonlocal keys
        if agent != "codex" or not args.uninstall or not scope or not codex_trust.installed(scope, home):
            return
        try:
            keys = codex_trust.okeanos_keys(scope, root, home)
        except Exception as e:  # noqa: BLE001 - a Codex failure never breaks the uninstall
            print(f"codex: aviso, não consegui ler os hooks pelo Codex ({e}); as entradas de confiança do Okeanos "
                  "em hooks.state ficam no config.toml do Codex (inofensivas sem os hooks; tire-as à mão se quiser).")

    outcome = installer.run(args.agent, uninstall=args.uninstall, dry_run=args.dry_run, project=args.project,
                            codex_hooks=args.codex_hooks, before=before)
    codex_done = scope is not None and "codex" in outcome.agents
    if codex_done and args.uninstall:
        if keys and outcome.code == 0:  # only once the Okeanos hooks are really gone
            try:
                removed = codex_trust.forget(scope, keys, root, home)
                if removed:
                    print(f"codex: {removed} entrada(s) de confiança do Okeanos removida(s) de hooks.state.")
            except Exception as e:  # noqa: BLE001
                print(f"codex: aviso, as entradas de confiança do Okeanos em hooks.state ficaram ({e}).")
        elif keys:
            print("codex: a desinstalação não terminou sem erro; as entradas de confiança do Okeanos em hooks.state "
                  "ficaram.")
        if scope.project:
            print("codex: se esta pasta está marcada como confiável no Codex, ela continua (pode ser anterior ao Okeanos).")
    elif codex_done and codex_trust.installed(scope, home):
        codex_trust.offer(scope, root, home, consent_refusal(), ask=True)
    return outcome.code


def cmd_codex_confiar(args):
    refusal = human_only("codex-confiar")
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    home, root = installer.home_dir(), installer.plugin_root()
    scope = codex_scope(args.project)
    if args.project and not scope:
        print("okeanos codex-confiar --project: aqui não é um repositório git; rode na raiz do projeto.", file=sys.stderr)
        return 1
    if not codex_trust.installed(scope, home):
        if not args.project and installer.orca_managed(home):
            print("okeanos codex-confiar: o Orca gerencia o Codex e não há hooks de usuário do Okeanos; "
                  "neste projeto use `okeanos codex-confiar --project`.", file=sys.stderr)
        else:
            install = "okeanos install --agent codex" + (" --project" if args.project else "")
            print(f"okeanos codex-confiar: os hooks do Okeanos não estão instalados aqui; rode `{install}`.",
                  file=sys.stderr)
        return 1
    return codex_trust.offer(scope, root, home, None, ask=not args.sim)


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
    print(f"instalação (em {installer.home_dir()}):")
    for agent, pieces in installer.status().items():
        print(f"  {agent}: " + (f"instalado ({', '.join(pieces)})" if pieces else "não instalado"))
    home = installer.home_dir()
    print(f"  codex, home gerenciado pelo Orca ({installer.codex_dir(home)}): {yes(installer.orca_managed(home))}")
    if root:
        print(f"  codex, hooks deste projeto ({installer.CODEX_PROJECT_HOOKS}): "
              f"{yes(installer.codex_project_installed(root))}")
        rule = os.path.join(root, installer.CURSOR_RULE)
        print(f"  cursor, regra deste projeto ({installer.CURSOR_RULE}): {yes(os.path.exists(rule))}")
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
    i = sub.add_parser("install", help="instala o Okeanos nos agentes encontrados (Claude Code, Codex, Copilot, Cursor)",
                       description="Detecta os agentes e instala em cada um: Claude Code pelo marketplace; "
                                   "Codex com skills em ~/.agents/skills, o bloco do processo no AGENTS.md global e os "
                                   "hooks no hooks.json do usuário (se o Orca gerencia o Codex, os hooks vão por "
                                   "projeto, com --project); Copilot com as mesmas skills, o bloco em "
                                   "~/.copilot/copilot-instructions.md e os hooks em ~/.copilot/hooks/okeanos.json; "
                                   "Cursor com as mesmas skills e os hooks em ~/.cursor/hooks.json (as regras do "
                                   "Cursor vão por projeto, com --project). "
                                   "Também liga a CLI em ~/.local/bin. Idempotente; edita só o que é do Okeanos e "
                                   "guarda <arquivo>.okeanos-bak antes de mudar.")
    i.add_argument("--agent", action="append", metavar="AGENTE",
                   help="só este agente (repita ou separe por vírgula): claude, codex, copilot, cursor")
    i.add_argument("--project", action="store_true",
                   help="no repositório atual: com --agent cursor, o processo como regra do Cursor "
                        "(.cursor/rules/okeanos.mdc); com --agent codex, os hooks em .codex/hooks.json")
    i.add_argument("--codex-hooks", choices=("toml", "json"),
                   help="onde ficam os hooks de usuário do Codex: json (hooks.json, o padrão) ou toml ([hooks] no "
                        "config.toml). Ignorado quando o Orca gerencia o Codex (aí use --project)")
    i.add_argument("--uninstall", action="store_true", help="remove só o que o Okeanos instalou")
    i.add_argument("--dry-run", action="store_true", help="mostra o que faria, sem mudar nada")
    i.set_defaults(func=cmd_install)
    c = sub.add_parser("codex-confiar", help="confia nos hooks do Okeanos no Codex (só num terminal interativo)",
                       description="Mostra os hooks do Okeanos, pergunta e registra a confiança pelo próprio Codex "
                                   "(codex app-server), só para os hooks do Okeanos que precisam de revisão. Útil "
                                   "depois de atualizar o Okeanos. Sem terminal ou dentro de um agente, recusa.")
    c.add_argument("--project", action="store_true", help="os hooks do projeto atual (.codex/hooks.json)")
    c.add_argument("--sim", action="store_true",
                   help="responde sim à pergunta dos hooks; com --project, a de marcar a pasta como confiável "
                        "no Codex continua sendo feita (ainda exige terminal interativo)")
    c.set_defaults(func=cmd_codex_confiar)
    sub.add_parser("doctor", help="mostra onde o Okeanos está e o que encontra aqui").set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)
