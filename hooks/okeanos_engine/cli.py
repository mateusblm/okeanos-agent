"""Command line: okeanos.py [--agent NAME] <hook> < payload.json, or okeanos.py metrics [days].

Fail-open: an unknown agent, unreadable stdin or any internal error ends in "allow".
"""

import json
import os
import sys
import time

from . import approvals, rules
from .dialects import DEFAULT, DIALECTS
from .model import ASK, BLOCK, DENY, Decision
from .plumbing import Context, metrics_path, repo_root


def split_agent(argv):
    """(agent, remaining args) from --agent NAME / --agent=NAME anywhere in argv."""
    agent, rest, i = DEFAULT, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--agent":
            agent = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            continue
        if a.startswith("--agent="):
            agent = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    return agent, rest


def combine(decisions):
    """One Decision for a tool call that touched several files: a deny wins, asks merge into one
    reason with a single `okeanos aprovar` line, blocks and notes are joined."""
    decisions = [d for d in decisions if not d.silent]
    if not decisions:
        return Decision()
    if len(decisions) == 1:
        return decisions[0]
    for d in decisions:
        if d.action == DENY:
            return d
    asks = [d for d in decisions if d.action == ASK]
    join = lambda parts: "\n".join(dict.fromkeys(p for p in parts if p))  # noqa: E731
    context, message = join(d.context for d in decisions), join(d.message for d in decisions)
    if asks:
        targets = list(dict.fromkeys(t for d in asks for t in d.targets))
        reasons = [d.reason.rsplit("\n", 1)[0] if d.targets else d.reason for d in asks]
        reason = join(reasons) + ("\n" + approvals.how_to(targets) if targets else "")
        return Decision(ASK, reason, context, message, targets)
    blocks = [d.reason for d in decisions if d.action == BLOCK]
    if blocks:
        return Decision(BLOCK, "\n\n".join(blocks), context, message)
    return Decision(context=context, message=message)


def handle(dialect, hook, data):
    """One hook call: payload -> Event(s) -> Decision -> (stdout, exit code)."""
    event, decision = None, Decision()
    try:
        parsed = dialect.parse(hook, data)
        events = parsed if isinstance(parsed, list) else ([parsed] if parsed is not None else [])
        decisions = []
        for e in events:
            root = repo_root(e.cwd or os.getcwd())
            decisions.append(rules.decide(e, Context(e, root)))
        event = events[0] if events else None
        decision = combine(decisions)
    except Exception:  # noqa: BLE001
        event, decision = None, Decision()  # a broken rule must never block work
    try:
        return dialect.render(hook, event, decision)
    except Exception:  # noqa: BLE001
        try:
            return dialect.render(hook, None, Decision())
        except Exception:  # noqa: BLE001
            return "", 0


def metrics_summary(days, by_agent=False, now=None):
    """Print event counts per kind (and per agent) for the current repo (used by retro and harness pruning)."""
    root = repo_root(os.getcwd())
    path = metrics_path(root) if root else None
    if not path or not os.path.exists(path):
        print("Sem métricas do Okeanos neste repositório ainda.")
        return
    since = (time.time() if now is None else now) - days * 86400
    counts, agents, sessions = {}, {}, set()
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if e.get("ts", 0) < since:
                continue
            counts[e.get("kind", "?")] = counts.get(e.get("kind", "?"), 0) + 1
            agent = e.get("agent") or "?"
            agents[agent] = agents.get(agent, 0) + 1
            sessions.add(e.get("session"))
    print(f"Okeanos, últimos {days} dias, {len(sessions)} sessões ({path}):")
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {kind}")
    if by_agent and agents:
        print("Por agente:")
        for agent, n in sorted(agents.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {agent}")


def main(argv=None):
    agent, args = split_agent(list(sys.argv[1:] if argv is None else argv))
    if args[:1] == ["metrics"]:
        metrics_summary(int(args[1]) if len(args) > 1 else 30)
        return 0
    dialect = DIALECTS.get(agent)
    if dialect is None or not args:
        return 0
    hook = args[0]
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        data = None
    if os.environ.get("OKEANOS_HOOK_DEBUG"):
        try:
            with open(os.path.expanduser("~/.okeanos-hook-debug.jsonl"), "a") as f:
                f.write(json.dumps({"agent": agent, "cmd": hook, "data": data}) + "\n")
        except Exception:  # noqa: BLE001
            pass
    text, code = handle(dialect, hook, data)
    if text:
        print(text)
    return code
