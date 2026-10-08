"""Command line: okeanos.py [--agent NAME] <hook> < payload.json, or okeanos.py metrics [days].

Fail-open: an unknown agent, unreadable stdin or any internal error ends in "allow".
"""

import json
import os
import sys
import time

from . import rules
from .dialects import DEFAULT, DIALECTS
from .model import Decision
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


def handle(dialect, hook, data):
    """One hook call: payload -> Event -> Decision -> (stdout, exit code)."""
    event, decision = None, Decision()
    try:
        event = dialect.parse(hook, data)
        if event is not None:
            root = repo_root(event.cwd or os.getcwd())
            decision = rules.decide(event, Context(event, root))
    except Exception:  # noqa: BLE001
        event, decision = None, Decision()  # a broken rule must never block work
    try:
        return dialect.render(hook, event, decision)
    except Exception:  # noqa: BLE001
        try:
            return dialect.render(hook, None, Decision())
        except Exception:  # noqa: BLE001
            return "", 0


def metrics_summary(days):
    """Print event counts per kind for the current repo (used by retro and harness pruning)."""
    root = repo_root(os.getcwd())
    path = metrics_path(root) if root else None
    if not path or not os.path.exists(path):
        print("Sem métricas do Okeanos neste repositório ainda.")
        return
    since = time.time() - days * 86400
    counts, sessions = {}, set()
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if e.get("ts", 0) < since:
                continue
            counts[e.get("kind", "?")] = counts.get(e.get("kind", "?"), 0) + 1
            sessions.add(e.get("session"))
    print(f"Okeanos, últimos {days} dias, {len(sessions)} sessões ({path}):")
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {kind}")


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
